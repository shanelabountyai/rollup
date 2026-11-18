"""Chart rules (D-42): the chart type follows the result shape, and the SVG shows only result cells."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rollup.ui.chart import MAX_BARS, choose_chart, fmt_cell, render_svg
from rollup.validator import validate_answer


def svg_text(svg: str) -> str:
    """All human-readable text in an SVG: text nodes, <title>s and aria-labels."""
    texts = re.findall(r">([^<>]+)<", svg) + re.findall(r'aria-label="([^"]*)"', svg)
    # Separate nodes with "; " so a value and the next label ("12.50", "b") don't read as one token ("12.50 b").
    return "; ".join(t.strip() for t in texts if t.strip())


def assert_svg_cites_only_cells(columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    spec = choose_chart(columns, rows)
    svg = render_svg(spec)
    assert svg, spec.reason
    text = svg_text(svg)
    report = validate_answer(text, columns, rows)
    assert report.ok, report.violations


MONTHS = [dt.date(2025, m, 1) for m in range(1, 7)]


def test_date_and_number_is_a_line() -> None:
    rows = [(d, 1000.5 * (i + 1)) for i, d in enumerate(MONTHS)]
    spec = choose_chart(["month", "spend"], rows)
    assert spec.kind == "line"
    assert (spec.x_column, spec.y_column) == ("month", "spend")
    assert spec.labels == [d.isoformat() for d in MONTHS]


def test_line_is_drawn_in_date_order_whatever_the_row_order() -> None:
    rows = [(d, i) for i, d in enumerate(MONTHS)][::-1]
    spec = choose_chart(["month", "n"], rows)
    assert spec.labels == [d.isoformat() for d in MONTHS]
    assert spec.values == [float(i) for i in range(6)]


def test_timestamp_column_counts_as_a_date() -> None:
    rows = [(dt.datetime(2025, 1, d), d) for d in (1, 8, 15)]
    assert choose_chart(["week_start", "leads"], rows).kind == "line"


def test_text_and_number_is_a_bar_in_result_order() -> None:
    rows = [("google_ads", Decimal("504434.47")), ("linkedin_ads", Decimal("369325.12")), ("meta_ads", 150788.76)]
    spec = choose_chart(["platform", "spend"], rows)
    assert spec.kind == "bar"
    assert spec.labels == ["google_ads", "linkedin_ads", "meta_ads"]
    assert spec.value_labels == ["504,434.47", "369,325.12", "150,788.76"]


def test_date_wins_over_text_and_first_numeric_column_is_charted() -> None:
    rows = [(d, "x" + str(i), i, i * 10) for i, d in enumerate(MONTHS)]
    spec = choose_chart(["month", "label", "a", "b"], rows)
    assert spec.kind == "line"
    assert spec.y_column == "a"


@pytest.mark.parametrize(
    ("columns", "rows", "truncated", "why"),
    [
        (["a", "b"], [], False, "No rows"),
        (["platform", "spend"], [("g", 1), ("m", 2)], True, "row cap"),
        (["platform", "spend"], [("g", 1)], False, "One row"),
        (["platform", "name"], [("g", "x"), ("m", "y")], False, "No numeric column"),
        (["year", "spend"], [(2025, 1.0), (2026, 2.0)], False, "No date or text column"),
        (["platform", "spend"], [("g", None), ("m", 2)], False, "NULL"),
        (["month", "channel", "spend"], [(MONTHS[0], "a", 1), (MONTHS[0], "b", 2)], False, "repeats"),
        (["platform", "spend"], [("g", 1), ("g", 2)], False, "repeats"),
        (["c", "n"], [(f"c{i}", i) for i in range(MAX_BARS + 1)], False, "More than"),
        (["flag", "n"], [(True, 1), (False, 2)], False, "No date or text column"),
    ],
)
def test_no_chart_cases(columns: list[str], rows: list[tuple[Any, ...]], truncated: bool, why: str) -> None:
    spec = choose_chart(columns, rows, truncated=truncated)
    assert spec.kind == "none"
    assert why in spec.reason
    assert render_svg(spec) == ""


def test_thirty_bars_is_still_a_bar() -> None:
    assert choose_chart(["c", "n"], [(f"c{i}", i) for i in range(MAX_BARS)]).kind == "bar"


def test_negative_values_draw_and_cite_only_cells() -> None:
    assert_svg_cites_only_cells(["channel", "delta"], [("a", -12.5), ("b", 30.0), ("c", 0)])


def test_flat_line_draws_one_value_label() -> None:
    rows = [(d, 5) for d in MONTHS]
    svg = render_svg(choose_chart(["month", "n"], rows))
    assert svg.count('class="val"') == 1


def test_labels_are_escaped() -> None:
    rows = [("<script>alert(1)</script>", 1), ("a&b", 2)]
    svg = render_svg(choose_chart(["name", "n"], rows))
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg and "a&amp;b" in svg


def test_fmt_cell() -> None:
    assert fmt_cell(1234567) == "1,234,567"
    assert fmt_cell(1234.5) == "1,234.50"
    assert fmt_cell(Decimal("0.123456")) == "0.1235"
    assert fmt_cell(dt.datetime(2025, 5, 1)) == "2025-05-01"
    assert fmt_cell(dt.datetime(2025, 5, 1, 13, 5)) == "2025-05-01 13:05:00"
    assert fmt_cell(None) == "NULL"
    assert fmt_cell(True) == "true"


_num = st.one_of(
    st.integers(min_value=-(10**9), max_value=10**9),
    st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False),
)


@given(st.lists(_num, min_size=2, max_size=MAX_BARS, unique=True))
def test_bar_svg_cites_only_cells(values: list[float]) -> None:
    assert_svg_cites_only_cells(["channel", "value"], [(f"chan_{chr(97 + i)}", v) for i, v in enumerate(values)])


@given(st.lists(_num, min_size=2, max_size=40))
def test_line_svg_cites_only_cells(values: list[float]) -> None:
    start = dt.date(2025, 1, 1)
    rows = [(start + dt.timedelta(days=7 * i), v) for i, v in enumerate(values)]
    assert_svg_cites_only_cells(["week_start", "value"], rows)
