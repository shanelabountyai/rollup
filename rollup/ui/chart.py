"""Pick a chart from the shape of a result set and draw it as inline SVG (Phase 4, D-42).

Rules, in order (the first that applies wins):

  no rows                                    -> none
  result hit the row cap (truncated)         -> none: a chart of a partial result would mislead
  one row                                    -> none: the table and the answer already say it
  no numeric column                          -> none
  a DATE/TIMESTAMP column + a numeric column -> line  (x = first date column, y = first numeric column,
                                                       points drawn in date order; dates must not repeat)
  a text column + a numeric column           -> bar   (label = first text column, value = first numeric column,
                                                       2..30 rows, labels must not repeat, drawn in result order)
  anything else                              -> none

Any NULL in the chosen x or y column -> none. Only the first numeric column is charted; the table shows the rest.

Honesty rule: every piece of text in the SVG is a result cell (formatted the way the table formats it) or a
column name. There are no axis ticks, gridline values, totals or percentages, so a chart can never show a number
that is not in the result. ``tests/test_chart.py`` checks this with the RU-03 validator.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from html import escape
from typing import Any, Literal

MAX_BARS = 30
WIDTH = 300  # viewBox width; sized for the chart card beside the table (design pass, D-55)

ChartKind = Literal["line", "bar", "none"]


def is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int | Decimal):
        return True
    return isinstance(v, float) and math.isfinite(v)


def is_date(v: Any) -> bool:
    return isinstance(v, dt.date)  # datetime is a subclass of date


def fmt_cell(v: Any) -> str:
    """Display format for table cells and chart labels: thousands separators, 2 decimals (4 below 1)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, Decimal | float):
        if isinstance(v, float) and not math.isfinite(v):
            return str(v)
        small = Decimal(0) < abs(Decimal(v)) < Decimal(1)
        return f"{v:,.4f}" if small else f"{v:,.2f}"
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) and v.tzinfo is None else v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


@dataclass(frozen=True)
class ChartSpec:
    kind: ChartKind
    reason: str
    x_column: str | None = None
    y_column: str | None = None
    labels: list[str] = field(default_factory=list)  # formatted x cells, in drawing order
    value_labels: list[str] = field(default_factory=list)  # formatted y cells, in drawing order
    values: list[float] = field(default_factory=list)  # y cells as floats, for geometry only (never printed)


def _column_kind(rows: Sequence[Sequence[Any]], i: int) -> str | None:
    """'date', 'number' or 'text' when every non-NULL cell in column i has that kind (and there is one)."""
    seen = [r[i] for r in rows if r[i] is not None]
    if not seen:
        return None
    if all(is_date(v) for v in seen):
        return "date"
    if all(is_number(v) for v in seen):
        return "number"
    if all(isinstance(v, str) for v in seen):
        return "text"
    return None


def _none(reason: str) -> ChartSpec:
    return ChartSpec(kind="none", reason=reason)


def choose_chart(columns: Sequence[str], rows: Sequence[Sequence[Any]], *, truncated: bool = False) -> ChartSpec:
    if not rows:
        return _none("No rows, so there is nothing to chart.")
    if truncated:
        return _none("The result hit the row cap, so a chart would show only part of it.")
    if len(rows) == 1:
        return _none("One row: the table and the answer already show it.")
    kinds = [_column_kind(rows, i) for i in range(len(columns))]
    numeric = [i for i, k in enumerate(kinds) if k == "number"]
    if not numeric:
        return _none("No numeric column to chart.")
    dates = [i for i, k in enumerate(kinds) if k == "date"]
    texts = [i for i, k in enumerate(kinds) if k == "text"]
    if dates:
        kind: ChartKind = "line"
        x = dates[0]
    elif texts:
        kind, x = "bar", texts[0]
    else:
        return _none("No date or text column to label a chart with.")
    y = numeric[0]
    if any(r[x] is None or r[y] is None for r in rows):
        return _none(f"`{columns[x]}` or `{columns[y]}` has NULL cells, so the chart is left out.")
    xs = [r[x] for r in rows]
    if len(set(xs)) != len(xs):
        return _none(f"`{columns[x]}` repeats (more than one series), so the table shows it instead.")
    ordered = list(rows)
    if kind == "line":
        ordered.sort(key=lambda r: r[x] if isinstance(r[x], dt.datetime) else dt.datetime.combine(r[x], dt.time()))
    elif len(rows) > MAX_BARS:
        return _none(f"More than {MAX_BARS} categories; the table is easier to read.")
    return ChartSpec(
        kind=kind,
        reason=(
            f"Line chart: `{columns[y]}` over `{columns[x]}` (a date column and a number)."
            if kind == "line"
            else f"Bar chart: `{columns[y]}` by `{columns[x]}` (a text column and a number)."
        ),
        x_column=columns[x],
        y_column=columns[y],
        labels=[fmt_cell(r[x]) for r in ordered],
        value_labels=[fmt_cell(r[y]) for r in ordered],
        values=[float(r[y]) for r in ordered],
    )


def _text(x: float, y: float, s: str, *, anchor: str = "start", cls: str = "lbl") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{cls}">{escape(s)}</text>'


def _bar_svg(spec: ChartSpec) -> str:
    row_h, bar_h, pad, value_w = 36, 14, 8, 92
    lo, hi = min(0.0, *spec.values), max(0.0, *spec.values)
    span = (hi - lo) or 1.0
    plot_w = WIDTH - 2 * pad - value_w
    zero_x = pad + (0 - lo) / span * plot_w
    height = pad * 2 + row_h * len(spec.values)
    parts = []
    for i, (label, vlabel, v) in enumerate(zip(spec.labels, spec.value_labels, spec.values, strict=True)):
        top = pad + i * row_h
        x0 = pad + (min(v, 0) - lo) / span * plot_w
        w = abs(v) / span * plot_w
        parts.append(_text(pad, top + 11, label))
        parts.append(
            f'<rect x="{x0:.1f}" y="{top + 15}" width="{max(w, 1):.1f}" height="{bar_h}" class="bar">'
            f"<title>{escape(label)}: {escape(vlabel)}</title></rect>"
        )
        parts.append(_text(pad + plot_w + 6, top + 27, vlabel, cls="val"))
    parts.append(f'<line x1="{zero_x:.1f}" y1="{pad}" x2="{zero_x:.1f}" y2="{height - pad}" class="axis" />')
    return _svg(spec, height, parts)


def _line_svg(spec: ChartSpec) -> str:
    height, pad_x, top, bottom = 230, 16, 24, 40
    plot_w, plot_h = WIDTH - 2 * pad_x, height - top - bottom
    lo, hi = min(spec.values), max(spec.values)
    span = (hi - lo) or 1.0
    n = len(spec.values)
    pts = [(pad_x + (i / (n - 1)) * plot_w, top + (1 - (v - lo) / span) * plot_h) for i, v in enumerate(spec.values)]
    parts = [f'<line x1="{pad_x}" y1="{top + plot_h}" x2="{pad_x + plot_w}" y2="{top + plot_h}" class="axis" />']
    parts.append('<polyline class="line" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '" />')
    for (x, y), label, vlabel in zip(pts, spec.labels, spec.value_labels, strict=True):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="pt">'
            f"<title>{escape(label)}: {escape(vlabel)}</title></circle>"
        )
    # Label the first and last dates, and the highest and lowest points, with their own cells.
    parts.append(_text(pts[0][0], height - 14, spec.labels[0]))
    parts.append(_text(pts[-1][0], height - 14, spec.labels[-1], anchor="end"))
    i_hi, i_lo = spec.values.index(hi), spec.values.index(lo)
    for i in dict.fromkeys((i_hi, i_lo)):  # both sit just above their point; one label if they coincide
        x, y = pts[i]
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        parts.append(_text(x, y - 8, spec.value_labels[i], anchor=anchor, cls="val"))
    return _svg(spec, height, parts)


def _svg(spec: ChartSpec, height: int, parts: list[str]) -> str:
    title = f"{spec.y_column} by {spec.x_column}"
    return (
        f'<svg class="chart chart-{spec.kind}" viewBox="0 0 {WIDTH} {height}" width="100%" role="img" '
        f'aria-label="{escape(title)}" xmlns="http://www.w3.org/2000/svg">'
        f"<title>{escape(title)}</title>" + "".join(parts) + "</svg>"
    )


def render_svg(spec: ChartSpec) -> str:
    """Inline SVG for a line or bar spec; empty string for ``none``."""
    if spec.kind == "bar":
        return _bar_svg(spec)
    if spec.kind == "line":
        return _line_svg(spec)
    return ""
