"""Question -> draft SQL -> guards -> run -> validated answer (PRD Text-to-SQL; Phase 3).

The draft goes through ``rollup.runner.execute_guarded`` exactly as Phase 2 built it: the guards run first and there
is no bypass. A question ends in exactly one status:

  answered          the draft passed the guards and ran; ``answer`` passed RU-03 (model paragraph or fallback)
  refused_question  the model said the marts cannot answer it (the PRD refusal path)
  refused_guard     the draft failed a guard; nothing executed
  query_error       DuckDB rejected a guarded draft (e.g. unknown column)
  timeout           the guarded draft ran past the timeout and was interrupted
  model_error       the model produced nothing usable

Only ``answered`` shows numbers. Every other status carries a reason and an answer with no digits in it.

    python -m rollup.ask "What was total paid spend by channel?"        # recorded model (offline)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from rollup.guards import DEFAULT_MAX_ROWS, GuardViolation
from rollup.llm import DraftModel, ModelUnavailable, RecordedModel
from rollup.runner import DEFAULT_TIMEOUT_S, QueryError, QueryResult, QueryTimeout, execute_guarded, open_readonly
from rollup.schema_context import SchemaContext, load_context
from rollup.validator import ValidationReport, fallback_answer, validate_answer

STATUSES = ("answered", "refused_question", "refused_guard", "query_error", "timeout", "model_error")

_REFUSAL_TEXT = {
    "refused_question": "This question can't be answered from the marketing marts.",
    "refused_guard": "The drafted SQL was refused by the safety checks, so nothing was run.",
    "query_error": "The drafted SQL could not be run against the marts.",
    "timeout": "The drafted SQL took too long and was stopped.",
    "model_error": "No usable SQL was drafted for this question.",
}


@dataclass
class AskResult:
    question: str
    status: str
    answer: str
    draft_sql: str | None = None
    executed_sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    truncated: bool = False
    elapsed_ms: float | None = None
    reason: str | None = None  # refusal / error detail
    guard_code: str | None = None
    answer_source: str | None = None  # "model" or "fallback" when answered
    model_answer: str | None = None  # the model's paragraph, kept for audit even when rejected
    validation: ValidationReport | None = None  # RU-03 report for the model's paragraph

    @property
    def answered(self) -> bool:
        return self.status == "answered"


def _refuse(question: str, status: str, reason: str, **kw: Any) -> AskResult:
    return AskResult(question=question, status=status, answer=_REFUSAL_TEXT[status], reason=reason, **kw)


def ask(
    question: str,
    model: DraftModel,
    con: duckdb.DuckDBPyConnection,
    context: SchemaContext,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> AskResult:
    """Answer one question on an open read-only connection (see ``open_readonly``)."""
    try:
        draft = model.draft_sql(question, context)
    except ModelUnavailable as e:
        return _refuse(question, "model_error", str(e))
    if draft.sql is None:
        return _refuse(question, "refused_question", draft.refusal or "refused")

    try:
        result: QueryResult = execute_guarded(con, draft.sql, max_rows=max_rows, timeout_s=timeout_s)
    except GuardViolation as e:
        return _refuse(question, "refused_guard", e.message, draft_sql=draft.sql, guard_code=e.code)
    except QueryTimeout as e:
        return _refuse(question, "timeout", str(e), draft_sql=draft.sql)
    except QueryError as e:
        return _refuse(question, "query_error", str(e), draft_sql=draft.sql)

    out = AskResult(
        question=question,
        status="answered",
        answer="",
        draft_sql=draft.sql,
        executed_sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        truncated=result.truncated,
        elapsed_ms=result.elapsed_ms,
    )
    try:
        paragraph = model.write_answer(question, result.sql, result.columns, result.rows).strip()
    except ModelUnavailable:
        paragraph = ""
    out.model_answer = paragraph
    out.validation = validate_answer(paragraph, result.columns, result.rows, question)
    if out.validation.ok:
        out.answer, out.answer_source = paragraph, "model"
    else:
        out.answer, out.answer_source = fallback_answer(result.columns, result.rows), "fallback"
        # The fallback quotes only result cells; re-check so RU-03 holds by construction, not by assumption.
        if not validate_answer(out.answer, result.columns, result.rows).ok:  # pragma: no cover - invariant
            raise AssertionError("fallback answer failed RU-03")
    return out


def _print(r: AskResult) -> None:
    print(f"Q: {r.question}\nstatus: {r.status}")
    if r.draft_sql:
        print(f"-- drafted SQL:\n{r.draft_sql}")
    if r.executed_sql:
        print(f"-- executed SQL (after guards):\n{r.executed_sql}\n")
        print(" | ".join(r.columns))
        for row in r.rows[:50]:
            print(" | ".join("NULL" if v is None else str(v) for v in row))
        more = len(r.rows) - 50
        print(
            f"({len(r.rows)} row(s){f', {more} not shown' if more > 0 else ''}"
            f"{', truncated at row cap' if r.truncated else ''})"
        )
    if r.reason:
        print(f"reason: {r.reason}" + (f" [{r.guard_code}]" if r.guard_code else ""))
    if r.validation and not r.validation.ok:
        print(f"model paragraph rejected by RU-03 validator: {'; '.join(r.validation.violations)}")
    print(f"\nanswer ({r.answer_source or 'refusal'}): {r.answer}")


EXIT_CODES = {
    "answered": 0,
    "refused_question": 1,
    "refused_guard": 2,
    "timeout": 3,
    "query_error": 4,
    "model_error": 5,
}


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rollup.ask", description="Ask the Rollup marts a question.")
    p.add_argument("question")
    p.add_argument(
        "--model",
        choices=["recorded", "live"],
        default="recorded",
        help="recorded fixtures (default, offline) or the live Anthropic adapter (needs a key)",
    )
    p.add_argument("--db", default=None)
    p.add_argument("--manifest", default=None)
    args = p.parse_args(argv)

    model: DraftModel
    if args.model == "live":
        from rollup.llm import AnthropicModel

        try:
            model = AnthropicModel()
        except ModelUnavailable as e:
            print(f"live model unavailable: {e}", file=sys.stderr)
            return EXIT_CODES["model_error"]
    else:
        model = RecordedModel()
    con = open_readonly(Path(args.db) if args.db else None)
    try:
        ctx = load_context(args.manifest)
        r = ask(args.question, model, con, ctx)
    finally:
        con.close()
    _print(r)
    return EXIT_CODES[r.status]


if __name__ == "__main__":
    sys.exit(main())
