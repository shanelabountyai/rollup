"""RU-03 answer validator: every number in an answer paragraph must appear in its result set (Phase 3, D-32).

Checking order, on a copy of the paragraph:

1. The paragraph must be non-empty and a single paragraph.
2. Text cells and column names are removed where they appear as whole words, so names that contain digits
   (``Webinar Search Q1 2026``, ``gads_1001``) are allowed exactly as the result spells them.
3. Date expressions are checked against the result's DATE/TIMESTAMP cells and removed: ISO dates and months
   (``2025-05-01``, ``2025-05``), US dates, ``May 2025``, ``May 1, 2025``, ``Q3 2025`` / ``2025-Q3``. A date
   expression that matches no date cell fails. A bare ``Q3`` or four-digit year is accepted when a date cell is in
   that quarter or year.
4. Every remaining run of digits is a number token and must match a numeric cell: written with ``d`` decimals it
   matches a cell within half a unit of the last written digit (so rounding is allowed, inventing is not).
   ``k``/``M``/``B`` (and ``thousand``/``million``/``billion``) scale the token. A ``%`` token matches a cell as a
   ratio x 100 or as a value already in percent. Signs are ignored (``fell 12%`` may cite ``-12``).

Derived numbers (sums, differences, row counts) are not in the result, so they fail by design. Numbers written as
words are not detected (a known limit, stated in the PR). ``fallback_answer`` builds a paragraph only from cells and
always validates.
"""

from __future__ import annotations

import bisect
import calendar
import datetime as dt
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_MONTH_RE = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

_ISO_DATETIME = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?))?(?!\d)")
_ISO_MONTH = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?![\d-])")
_US_DATE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_MONTH_DAY_YEAR = re.compile(_MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", re.IGNORECASE)
_DAY_MONTH_YEAR = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH_RE + r",?\s+(\d{4})(?!\d)", re.IGNORECASE)
_MONTH_YEAR = re.compile(r"\b" + _MONTH_RE + r",?\s+(\d{4})(?!\d)", re.IGNORECASE)
_QUARTER_YEAR = re.compile(r"\b(?:Q([1-4])[\s-]+(\d{4})|(\d{4})[\s-]+Q([1-4]))(?!\d)", re.IGNORECASE)
_QUARTER = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)
_YEAR = re.compile(
    r"(?<![\d.,$])((?:19|20)\d{2})(?!\d|[.,]\d|\s*%|\s*(?:k|m|mm|b|bn|million|billion|thousand|percent|pct)\b)",
    re.IGNORECASE,
)

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_SUFFIX = re.compile(
    r"\s*(%|percent\b|pct\b|k\b|m\b|mm\b|b\b|bn\b|thousand\b|million\b|billion\b|st\b|nd\b|rd\b|th\b)", re.IGNORECASE
)
_SCALES = {"k": 3, "thousand": 3, "m": 6, "mm": 6, "million": 6, "b": 9, "bn": 9, "billion": 9}


@dataclass
class ValidationReport:
    ok: bool
    checked: list[str] = field(default_factory=list)  # number/date tokens that matched the result
    violations: list[str] = field(default_factory=list)  # human-readable reasons


@dataclass(frozen=True)
class _Pool:
    numbers: list[Decimal]  # sorted absolute values of numeric cells
    dates: frozenset[dt.date]
    datetimes: tuple[str, ...]  # 'YYYY-MM-DD HH:MM:SS[.ffffff]' for timestamp cells
    texts: tuple[str, ...]  # text cells and column names, longest first


def _to_decimal(v: Any) -> Decimal | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, Decimal):
        return abs(v) if v.is_finite() else None
    if isinstance(v, int):
        return Decimal(abs(v))
    if isinstance(v, float):
        return Decimal(abs(v)) if math.isfinite(v) else None  # exact binary value
    return None


def _build_pool(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> _Pool:
    numbers: list[Decimal] = []
    dates: set[dt.date] = set()
    datetimes: list[str] = []
    texts: set[str] = {c for c in columns if c}
    for row in rows:
        for v in row:
            if v is None or isinstance(v, bool):
                continue
            d = _to_decimal(v)
            if d is not None:
                numbers.append(d)
            elif isinstance(v, dt.datetime):
                dates.add(v.date())
                datetimes.append(v.isoformat(sep=" "))
            elif isinstance(v, dt.date):
                dates.add(v)
            elif isinstance(v, str) and v.strip():
                texts.add(v.strip())
                try:
                    parsed = Decimal(v.strip().replace(",", ""))
                except InvalidOperation:
                    continue
                if parsed.is_finite():
                    numbers.append(abs(parsed))
    numbers.sort()
    return _Pool(
        numbers=numbers,
        dates=frozenset(dates),
        datetimes=tuple(datetimes),
        texts=tuple(sorted(texts, key=len, reverse=True)),
    )


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _remove_texts(text: str, pool: _Pool) -> str:
    for t in pool.texts:
        if not any(ch.isdigit() for ch in t):
            continue  # nothing to protect
        # Whole words only, never inside a number or date such as 0.01, 1,500 or 2000-01-01 00:00.
        pat = re.compile(r"(?<!\w)(?<!\d[.,:/-])" + re.escape(t) + r"(?!\w)(?![.,:/-]\d)", re.IGNORECASE)
        text = pat.sub(lambda m: " " * len(m.group(0)), text)
    return text


def _safe_date(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _check_dates(text: str, pool: _Pool, report: ValidationReport) -> str:
    def has_month(y: int, m: int) -> bool:
        return any(d.year == y and d.month == m for d in pool.dates)

    def has_quarter(y: int | None, q: int) -> bool:
        return any((y is None or d.year == y) and (d.month - 1) // 3 + 1 == q for d in pool.dates)

    def consume(pattern: re.Pattern[str], judge: Any) -> None:
        nonlocal text
        for m in list(pattern.finditer(text)):
            if not m.group(0).strip():
                continue
            ok = judge(m)
            (report.checked if ok else report.violations).append(
                m.group(0) if ok else f"date {m.group(0)!r} is not in the result"
            )
            text = _blank(text, m.start(), m.end())

    def iso(m: re.Match[str]) -> bool:
        day = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if day is None:
            return False
        if m.group(4):
            stamp = m.group(0).replace("T", " ")
            return any(s.startswith(stamp) for s in pool.datetimes)
        return day in pool.dates

    def us(m: re.Match[str]) -> bool:
        return _safe_date(int(m.group(3)), int(m.group(1)), int(m.group(2))) in pool.dates

    def mdy(m: re.Match[str]) -> bool:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))) in pool.dates

    def dmy(m: re.Match[str]) -> bool:
        return _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))) in pool.dates

    def iso_month(m: re.Match[str]) -> bool:
        return 1 <= int(m.group(2)) <= 12 and has_month(int(m.group(1)), int(m.group(2)))

    def month_year(m: re.Match[str]) -> bool:
        return has_month(int(m.group(2)), _MONTHS[m.group(1).lower()])

    def quarter_year(m: re.Match[str]) -> bool:
        q, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        return has_quarter(int(y), int(q))

    def quarter(m: re.Match[str]) -> bool:
        return has_quarter(None, int(m.group(1)))

    def year(m: re.Match[str]) -> bool:
        y = int(m.group(1))
        if any(d.year == y for d in pool.dates):
            return True
        return _match_number(Decimal(y), 0, 0, False, pool)

    consume(_ISO_DATETIME, iso)
    consume(_US_DATE, us)
    consume(_MONTH_DAY_YEAR, mdy)
    consume(_DAY_MONTH_YEAR, dmy)
    consume(_ISO_MONTH, iso_month)
    consume(_MONTH_YEAR, month_year)
    consume(_QUARTER_YEAR, quarter_year)
    consume(_QUARTER, quarter)
    consume(_YEAR, year)
    return text


def _in_pool(target: Decimal, tol: Decimal, numbers: list[Decimal]) -> bool:
    i = bisect.bisect_left(numbers, target - tol)
    return i < len(numbers) and numbers[i] <= target + tol


def _match_number(value: Decimal, decimals: int, scale: int, percent: bool, pool: _Pool) -> bool:
    # Half a unit of the last written digit, plus a hair for binary floats in the result.
    tol = Decimal(5) * Decimal(10) ** (-(decimals + 1)) * (Decimal(1) + Decimal("1e-9"))
    unscaled = value * Decimal(10) ** scale
    tol_unscaled = tol * Decimal(10) ** scale
    if _in_pool(unscaled, tol_unscaled, pool.numbers):
        return True
    return percent and _in_pool(value / 100, tol / 100, pool.numbers)


def _tokens(raw: str) -> list[str]:
    """Split a digit run on commas unless it is a well-formed thousands-grouped number."""
    if "," not in raw or _GROUPED.match(raw):
        return [raw.replace(",", "")]
    return [p for p in raw.split(",") if p]


def _check_numbers(text: str, pool: _Pool, report: ValidationReport) -> None:
    for m in _NUMBER.finditer(text):
        raw = m.group(0).rstrip(",")
        suffix_m = _SUFFIX.match(text, m.start() + len(raw))
        suffix = suffix_m.group(1).lower() if suffix_m else ""
        for i, tok in enumerate(parts := _tokens(raw)):
            last = i == len(parts) - 1
            decimals = len(tok.split(".")[1]) if "." in tok else 0
            scale = _SCALES.get(suffix, 0) if last else 0
            percent = last and suffix in {"%", "percent", "pct"}
            shown = tok + (suffix if last and suffix not in {"st", "nd", "rd", "th"} else "")
            if _match_number(Decimal(tok), decimals, scale, percent, pool):
                report.checked.append(shown)
            else:
                report.violations.append(f"number {shown!r} is not in the result")


def validate_answer(paragraph: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> ValidationReport:
    """Check one answer paragraph against the result it describes (RU-03)."""
    with localcontext() as ctx:
        ctx.prec = 800  # exact for any finite double and any DECIMAL(38); the default 28 digits would round
        return _validate(paragraph, columns, rows)


def _validate(paragraph: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> ValidationReport:
    report = ValidationReport(ok=False)
    if not paragraph or not paragraph.strip():
        report.violations.append("answer is empty")
        return report
    if re.search(r"\n\s*\n", paragraph.strip()):
        report.violations.append("answer is more than one paragraph")
    pool = _build_pool(columns, rows)
    text = _remove_texts(paragraph, pool)
    text = _check_dates(text, pool, report)
    _check_numbers(text, pool, report)
    report.ok = not report.violations
    return report


def _fmt(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, Decimal | float):
        if isinstance(v, float) and not math.isfinite(v):
            return "not a number"
        return f"{v:,.2f}"
    if isinstance(v, dt.datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


def fallback_answer(columns: Sequence[str], rows: Sequence[Sequence[Any]], max_rows: int = 3) -> str:
    """Deterministic paragraph quoting only result cells (used when the model's paragraph fails RU-03)."""
    if not rows:
        return "The query returned no rows, so there is nothing to report for this question."
    parts = []
    for row in rows[:max_rows]:
        parts.append(", ".join(f"{c} {_fmt(v)}" for c, v in zip(columns, row, strict=True)))
    lead = "The result has one row: " if len(rows) == 1 else "The first rows of the result are: "
    tail = "" if len(rows) <= max_rows else " The full result is in the table."
    return lead + "; ".join(parts) + "." + tail
