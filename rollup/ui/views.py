"""Presentation helpers for the design pass (docs/design/*.dc.html): wording, highlighting and page data.

Everything here is display only. Nothing runs SQL, changes what ``ask`` decided, or computes a number that is
shown: the answer is highlighted, not rewritten (its plain text is unchanged), guard explanations are fixed
strings keyed by the guard code, and the eval page reads a committed run file (D-44).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape

from rollup.guards import DEFAULT_MAX_ROWS
from rollup.llm import DEFAULT_RECORDING
from rollup.runner import DEFAULT_TIMEOUT_S
from rollup.schema_context import REPO_ROOT, SchemaContext
from rollup.ui.chart import fmt_cell, is_date, is_number

TIMEOUT_S = DEFAULT_TIMEOUT_S  # re-exported so app.py keeps its narrow runner imports
EVAL_RUN_FILE = REPO_ROOT / "docs" / "eval" / "recorded-run.json"

# Start page "Try:" questions (Start.dc.html): recorded ids chosen to show each kind of outcome.
STARTER_IDS: tuple[tuple[str, str], ...] = (
    ("03_top5_campaigns_lifetime_spend", "answer + bar chart"),
    ("15_won_revenue_by_close_month", "line chart"),
    ("r07_delete", "a guard refusal"),
    ("r01_nps", "the data can't answer"),
)


def starters(path: Path = DEFAULT_RECORDING) -> list[dict[str, str]]:
    """The starter questions, taken verbatim from the recording (never invented)."""
    by_id = {str(r["id"]): str(r["question"]) for r in json.loads(path.read_text(encoding="utf-8"))["responses"]}
    return [{"question": by_id[i], "shows": shows} for i, shows in STARTER_IDS if i in by_id]


# ---- guard wording (Refusal.dc.html) ---------------------------------------------------------------------

GUARD_EXPLAINERS: dict[str, tuple[str, str]] = {
    "not_select": (
        "Not run: Rollup only reads data",
        "The drafted SQL was not a plain SELECT: it would change or manage data. Rollup runs a single SELECT on a "
        "read-only connection, so nothing was changed and nothing ran. Ask the reporting question on its own.",
    ),
    "multiple_statements": (
        "Not run: one query at a time",
        "The drafted SQL held more than one statement. Rollup runs exactly one SELECT, so nothing ran. "
        "Try asking for one result at a time.",
    ),
    "table_not_allowed": (
        "Not run: that table is off limits",
        "The drafted SQL read a table outside the marts. Questions may read only the marts listed in Data docs "
        "(not staging, intermediate or system tables), so nothing ran.",
    ),
    "table_function": (
        "Not run: no reading files or table functions",
        "The drafted SQL tried to read data through a table function (for example a file reader) instead of a mart. "
        "Only the marts can be read, so nothing ran.",
    ),
    "function_not_allowed": (
        "Not run: that function is blocked",
        "The drafted SQL called a system or file function that is not allowed, so nothing ran.",
    ),
    "star_on_fact_table": (
        "Not run: name the columns you need",
        "The drafted SQL used SELECT * on a fact table. Fact tables must be read column by column, so nothing ran. "
        "Ask for the specific fields you want.",
    ),
    "bad_limit": (
        "Not run: the row limit was not a plain number",
        "The drafted SQL used a LIMIT the guards can't cap safely, so nothing ran.",
    ),
    "parse_error": (
        "Not run: the SQL could not be parsed",
        "The drafted SQL is not valid SQL for this warehouse, so the guards could not check it and nothing ran.",
    ),
    "unresolvable": (
        "Not run: the tables could not be resolved",
        "The guards could not work out which tables the drafted SQL reads, so nothing ran.",
    ),
    "empty": ("Not run: the draft was empty", "The model returned no SQL to check, so nothing ran."),
    "too_long": (
        "Not run: the draft was too long",
        "The drafted SQL was longer than the guards accept, so nothing ran.",
    ),
}
_GENERIC_GUARD = ("Not run: a safety check said no", "The drafted SQL failed a guard, so nothing ran.")


def guard_explainer(code: str | None) -> tuple[str, str]:
    return GUARD_EXPLAINERS.get(code or "", _GENERIC_GUARD)


_MART_REF = re.compile(r"\bmarts\.([a-z_][a-z0-9_]*)", re.IGNORECASE)


def marts_read(executed_sql: str | None) -> list[str]:
    """Mart names in the executed SQL (the guards pin every table to ``marts.``, D-26). Display only."""
    seen: dict[str, None] = {}
    for m in _MART_REF.finditer(executed_sql or ""):
        seen[m.group(1).lower()] = None
    return list(seen)


def passed_checks(executed_sql: str | None, elapsed_ms: float | None) -> list[str]:
    """The guard list for an answered question (Main.dc.html), worded from facts the page already has."""
    marts = marts_read(executed_sql)
    tables = f" ({', '.join(marts)})" if marts else ""
    timing = (
        f"finished in {elapsed_ms:g} ms, under the {DEFAULT_TIMEOUT_S:g} s timeout"
        if elapsed_ms is not None
        else f"ran under the {DEFAULT_TIMEOUT_S:g} s timeout"
    )
    return [
        "one SELECT statement, parsed",
        f"only allowlisted marts{tables}",
        "no SELECT * on a fact table",
        f"row limit added ({DEFAULT_MAX_ROWS:,})",
        "read-only connection",
        timing,
    ]


# ---- answer highlighting (Main.dc.html: highlighted numbers point at their cell) -------------------------

_TOKEN = re.compile(r"(?<![\w.\-])(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}(?![\d-])|\d[\d,]*(?:\.\d+)?)(?!\w)")


def _num(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _cell_matches(token: str, value: Any) -> bool:
    if value is None:
        return False
    if is_date(value):
        return fmt_cell(value).startswith(token) and len(token) in (7, 10)
    if is_number(value):
        t = _num(token)
        if t is None:
            return False
        if fmt_cell(value).replace(",", "") == token.replace(",", ""):
            return True
        try:
            return Decimal(str(value)) == t
        except InvalidOperation:
            return False
    return False


@dataclass
class Highlighted:
    html: Markup
    cited: set[tuple[int, int]]  # (row, column) of cells a highlighted number points to


def highlight_answer(answer: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> Highlighted:
    """Wrap each number in the (already RU-03-validated) answer in <mark>; link it to the first cell it equals.

    The text is not changed: stripping the tags gives back ``answer`` exactly. A number with no exact cell (for
    example one RU-03 matched after rounding, or one restated from the question, D-38) is marked but not linked.
    """
    parts: list[str] = []
    cited: set[tuple[int, int]] = set()
    pos = 0
    for m in _TOKEN.finditer(answer):
        token = m.group(1).rstrip(",")
        start, end = m.start(1), m.start(1) + len(token)
        if not token:
            continue
        parts.append(str(escape(answer[pos:start])))
        cell = next(
            ((i, j) for i, row in enumerate(rows) for j, v in enumerate(row) if _cell_matches(token, v)),
            None,
        )
        if cell is None:
            parts.append(
                f'<mark class="cite" title="Checked against the result at the precision written">{escape(token)}</mark>'
            )
        else:
            i, j = cell
            cited.add(cell)
            col = columns[j] if j < len(columns) else ""
            parts.append(
                f'<a class="cite" href="#cell-{i}-{j}" title="Row {i + 1}, {escape(col)}">'
                f"<mark>{escape(token)}</mark></a>"
            )
        pos = end
    parts.append(str(escape(answer[pos:])))
    return Highlighted(Markup("".join(parts)), cited)


# ---- eval page (Eval.dc.html) ----------------------------------------------------------------------------

OUTCOME_LABELS = {
    "answered": "Answered",
    "refused_question": "Model said the data can't answer",
    "refused_guard": "Refused by a guard",
    "query_error": "Database rejected the SQL",
    "timeout": "Timed out",
    "model_error": "No usable draft",
}


@dataclass
class EvalRow:
    n: str
    question: str
    set: str
    outcome: str
    result: str  # "pass", "fail" or "refused"
    result_label: str


@dataclass
class EvalView:
    source: str
    model: str
    golden_total: int
    golden_equivalent: int
    refusal_total: int
    refusal_correct: int
    invariant_failures: int
    db_unchanged: bool
    rejected_ru03: int
    rows: list[EvalRow]


def load_eval(path: Path = EVAL_RUN_FILE) -> EvalView | None:
    """The committed recorded-model run file, as the eval page shows it. ``None`` if the file is missing.

    Only summary counts, question text, status and the pass/fail flag are used. Answers, reasons and the model's
    rejected paragraphs are not read into the view (D-43).
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    s = data["summary"]
    rows: list[EvalRow] = []
    for item in data["items"]:
        qid = str(item["id"])
        status = str(item["status"])
        outcome = OUTCOME_LABELS.get(status, status)
        if status == "refused_guard" and item.get("guard_code"):
            outcome = f"{outcome} ({item['guard_code']})"
        if item["set"] == "golden":
            n = qid.split("_", 1)[0].lstrip("0") or "0"
            ok = bool(item.get("equivalent"))
            result, label = ("pass", "Pass") if ok else ("fail", "Fail")
        else:
            n = "R" + (qid.split("_", 1)[0].lstrip("r").lstrip("0") or "0")
            ok = bool(item.get("correct"))
            result, label = ("refused", "Correctly refused") if ok else ("fail", "Fail: showed numbers")
        rows.append(EvalRow(n, str(item["question"]), str(item["set"]), outcome, result, label))
    try:
        source = str(path.relative_to(REPO_ROOT))
    except ValueError:
        source = path.name
    return EvalView(
        source=source,
        model=str(data.get("model", "")),
        golden_total=int(s["golden_total"]),
        golden_equivalent=int(s["golden_equivalent"]),
        refusal_total=int(s["refusal_total"]),
        refusal_correct=int(s["refusal_correct"]),
        invariant_failures=int(s["invariant_failures"]),
        db_unchanged=bool(s["db_unchanged"]),
        rejected_ru03=int(s["model_paragraphs_rejected_ru03"]),
        rows=rows,
    )


# ---- data docs (DataDocs.dc.html) ------------------------------------------------------------------------


def first_sentence(text: str) -> str:
    one = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", one)
    return m.group(1) if m else one


def marts_summary(ctx: SchemaContext) -> list[dict[str, str]]:
    return [{"name": t.name, "summary": first_sentence(t.description)} for t in ctx.tables]
