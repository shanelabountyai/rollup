"""RU-03: every number in an answer paragraph appears in its result set."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from rollup.validator import fallback_answer, validate_answer

COLS = ["month_start", "channel_key", "spend_usd", "new_customers", "cac_usd", "ctr", "win_rate_pct", "campaign_name"]
ROWS: list[tuple[Any, ...]] = [
    (dt.date(2025, 5, 1), "paid_search", Decimal("123456.78"), 19, 6497.725263, 0.007471, 24.29, "Brand Search"),
    (
        dt.date(2026, 1, 1),
        "paid_social",
        Decimal("98920.87"),
        8,
        12365.10875,
        0.005893,
        26.18,
        "Webinar Search Q1 2026",
    ),
    (dt.datetime(2026, 3, 1, 14, 30), "li_2001", Decimal("-1500.00"), 0, None, 1.0, 0.0, "ABM Enterprise Q3 2025"),
]


def ok(p: str) -> bool:
    return validate_answer(p, COLS, ROWS).ok


@pytest.mark.parametrize(
    "paragraph",
    [
        "Paid search spent $123,456.78 in May 2025.",
        "Paid search spent 123456.78.",
        "Paid search spent about $123,457, roughly $123.5k or $0.12M.",
        "That is $123 thousand, or 0.1 million.",
        "CAC was $6,497.73 for paid search and $12,365 for paid social.",
        "CAC was $6.5k.",
        "Paid search CTR was 0.75% and paid social 0.59%.",
        "Win rate was 24.29% and 26.2 percent.",
        "Paid search won 19 customers and paid social 8.",
        "In 2025-05 and on 2026-01-01 spend moved; see also 2026-03-01 14:30.",
        "On May 1, 2025 and 1 January 2026 and 5/1/2025.",
        "Spend in Q2 2025 and 2026-Q1 differs; Q2 was larger.",
        "The 2026 numbers cover January 2026.",
        "Webinar Search Q1 2026 and ABM Enterprise Q3 2025 are campaigns; li_2001 was refunded 1,500.",
        "Spend fell by $1,500.00.",
        "The li_2001 rate was 100% and its CAC is null.",
        "The 1st month had 19 customers.",
        "No digits at all here.",
    ],
)
def test_honest_paragraphs_validate(paragraph: str) -> None:
    report = validate_answer(paragraph, COLS, ROWS)
    assert report.ok, report.violations


@pytest.mark.parametrize(
    ("paragraph", "bad"),
    [
        ("Total spend was $222,377.65.", "222377.65"),  # a derived sum
        ("Paid search spent $123,456.79.", "123456.79"),  # off in the last written digit
        ("Paid search spent about $124k.", "124k"),
        ("Paid search spent $0.2M.", "0.2m"),
        ("CTR was 0.8%.", "0.8%"),
        ("Win rate rose 1.89 points.", "1.89"),  # a difference
        ("We won 27 customers.", "27"),
        ("The top 3 channels.", "3"),
        ("There are 3 rows.", "3"),
        ("Campaign li_9999 spent nothing.", "9999"),
        ("Spend in December 2025.", "December 2025"),
        ("On 2025-05-02 spend rose.", "2025-05-02"),
        ("In Q4 2025 spend rose.", "Q4 2025"),
        ("In 2024 spend rose.", "2024"),
        ("At 2026-03-01 09:00 spend rose.", "2026-03-01 09:00"),
        ("Spend grew 12%.", "12%"),
    ],
)
def test_invented_numbers_fail(paragraph: str, bad: str) -> None:
    report = validate_answer(paragraph, COLS, ROWS)
    assert not report.ok
    assert any(bad.lower() in v.lower() for v in report.violations), report.violations


def test_empty_and_multi_paragraph_answers_fail() -> None:
    assert not validate_answer("", COLS, ROWS).ok
    assert not validate_answer("   ", COLS, ROWS).ok
    assert not validate_answer("Paid search won 19.\n\nPaid social won 8.", COLS, ROWS).ok
    assert validate_answer("Paid search won 19.\nPaid social won 8.", COLS, ROWS).ok


def test_digit_text_cells_only_protect_whole_words() -> None:
    cols, rows = ["k", "v"], [("1", 7)]
    assert validate_answer("Key 1 has 7.", cols, rows).ok
    assert not validate_answer("Key 12 has 7.", cols, rows).ok  # "1" must not hide the 1 inside 12


def test_column_names_with_digits_are_allowed() -> None:
    assert validate_answer("q1_spend is 5.", ["q1_spend"], [(5,)]).ok


def test_list_of_small_numbers_split_on_commas() -> None:
    assert validate_answer("Weeks 1,2 had 7.", ["w", "v"], [(1, 7), (2, 7)]).ok
    assert not validate_answer("Weeks 1,2,3 had 7.", ["w", "v"], [(1, 7), (2, 7)]).ok


def test_fallback_on_known_rows_validates() -> None:
    text = fallback_answer(COLS, ROWS)
    assert validate_answer(text, COLS, ROWS).ok
    assert "paid_search" in text
    assert not re.search(r"\d", fallback_answer(COLS, []))


# --- properties -------------------------------------------------------------------------------------------------

cells = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**12), max_value=10**12),
    st.decimals(min_value=-(10**9), max_value=10**9, places=2, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1e9, max_value=1e9, allow_nan=False, allow_infinity=False),
    st.floats(allow_nan=True, allow_infinity=True),
    st.dates(min_value=dt.date(1990, 1, 1), max_value=dt.date(2099, 12, 31)),
    st.datetimes(min_value=dt.datetime(1990, 1, 1), max_value=dt.datetime(2099, 12, 31)),
    st.text(alphabet="abcxyz_ 0123456789-Q", min_size=0, max_size=12),
)


@st.composite
def results(draw: st.DrawFn) -> tuple[list[str], list[tuple[Any, ...]]]:
    n_cols = draw(st.integers(1, 5))
    cols = [draw(st.from_regex(r"[a-z][a-z_0-9]{0,8}", fullmatch=True)) for _ in range(n_cols)]
    rows = draw(st.lists(st.tuples(*[cells] * n_cols), min_size=0, max_size=6))
    return cols, rows


@given(results())
def test_fallback_always_validates(res: tuple[list[str], list[tuple[Any, ...]]]) -> None:
    cols, rows = res
    report = validate_answer(fallback_answer(cols, rows), cols, rows)
    assert report.ok, report.violations


def _numbers(rows: list[tuple[Any, ...]]) -> list[Decimal]:
    out: list[Decimal] = []
    for r in rows:
        for v in r:
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, int | Decimal):
                out.append(abs(Decimal(v)))
            elif isinstance(v, float) and v == v and abs(v) != float("inf"):
                out.append(abs(Decimal(repr(v))))
            elif isinstance(v, str):
                out += [Decimal(x) for x in re.findall(r"\d+", v)]
    return out


@given(results(), st.decimals(min_value=0, max_value=10**9, places=2, allow_nan=False, allow_infinity=False))
def test_any_number_not_in_the_result_is_rejected(res: tuple[list[str], list[tuple[Any, ...]]], extra: Decimal) -> None:
    cols, rows = res
    # The extra number must be farther than the rounding tolerance from every result number; avoid year-like
    # integers that a date cell could legitimately support.
    assume(all(abs(extra - x) > Decimal("0.01") for x in _numbers(rows)))
    assume(not any(re.search(r"\d", c) for c in cols))
    shown = f"{extra:,.2f}"
    paragraph = fallback_answer(cols, rows) + f" The total was {shown}."
    assert not validate_answer(paragraph, cols, rows).ok
