"""The SQL-drafting model, behind an interface (Phase 3, D-29).

A ``DraftModel`` does two things: draft one SELECT against the marts for a question (or refuse), and write a
one-paragraph answer from a result set. Nothing a model returns is trusted: drafts go through the Phase 2 guards and
read-only runner, and answer paragraphs go through the RU-03 validator.

Implementations:
  RecordedModel   committed fixture responses (``rollup/eval/recorded.json``); what tests, CI and ``make eval`` use
  ReferenceModel  drafts the golden reference SQL; proves the eval harness can score 40/40
  AnthropicModel  optional live adapter (``pip install -e '.[live]'``, ``ANTHROPIC_API_KEY`` and
                  ``ROLLUP_LLM_MODEL`` set). Never called in tests or CI; running it is an owner hand step.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rollup.schema_context import SchemaContext

REFUSE_PREFIX = "REFUSE:"
DEFAULT_RECORDING = Path(__file__).resolve().parent / "eval" / "recorded.json"

SQL_SYSTEM_PROMPT = f"""You write DuckDB SQL for a marketing analytics warehouse.
Rules:
- Answer with exactly one SELECT statement (CTEs allowed) in a ```sql fenced block and nothing else.
- Read only the tables listed in the schema below, always schema-qualified as marts.<table>.
- Never use * on fct_* tables; name the columns you need. COUNT(*) is fine.
- Do not write, create, attach, copy, set or call anything; only read.
- Attribution: first touch is the primary credit (columns without a suffix); *_last_touch columns are last touch.
- If the tables cannot answer the question, reply with one line: {REFUSE_PREFIX} <short reason>
"""

ANSWER_SYSTEM_PROMPT = """You explain a SQL result to a marketing operations manager in one short paragraph.
Rules:
- Cite only numbers that appear in the result rows. You may round them or add thousands separators, % or $.
- Do not compute new numbers (no sums, differences, ratios, counts of rows) and do not spell numbers as words.
- One paragraph, plain text, no lists or headings.
"""


class ModelUnavailable(Exception):
    """The model could not produce a response (no recording, no key, network or SDK error)."""


@dataclass(frozen=True)
class Draft:
    raw: str
    sql: str | None
    refusal: str | None


_FENCE = re.compile(r"```(?:sql|duckdb)?\s*\n?(.*?)```", re.IGNORECASE | re.DOTALL)


def parse_draft(raw: str) -> Draft:
    """Turn a model's raw text into SQL or a refusal. The SQL is not checked here; the guards do that."""
    text = raw.strip()
    if text.upper().startswith(REFUSE_PREFIX):
        return Draft(raw=raw, sql=None, refusal=text[len(REFUSE_PREFIX) :].strip() or "refused")
    m = _FENCE.search(text)
    sql = (m.group(1) if m else text).strip()
    if not sql:
        return Draft(raw=raw, sql=None, refusal="model returned no SQL")
    return Draft(raw=raw, sql=sql, refusal=None)


def build_sql_prompt(question: str, context: SchemaContext) -> tuple[str, str]:
    """(system, user) messages for drafting."""
    return SQL_SYSTEM_PROMPT + "\nSchema:\n" + context.render(), f"Question: {question.strip()}"


def _fmt_cell(v: Any) -> str:
    return "NULL" if v is None else str(v)


def build_answer_prompt(
    question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> tuple[str, str]:
    lines = [" | ".join(columns)] + [" | ".join(_fmt_cell(v) for v in r) for r in rows[:50]]
    more = "" if len(rows) <= 50 else "\n(more rows not shown)"
    user = f"Question: {question.strip()}\n\nSQL:\n{sql}\n\nResult:\n" + "\n".join(lines) + more
    return ANSWER_SYSTEM_PROMPT, user


class DraftModel(Protocol):
    name: str

    def draft_sql(self, question: str, context: SchemaContext) -> Draft: ...

    def write_answer(self, question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str: ...


def normalize_question(q: str) -> str:
    return " ".join(q.split()).lower()


class RecordedModel:
    """Replays committed responses keyed by question text. No network."""

    def __init__(self, path: Path | str = DEFAULT_RECORDING) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.name = str(data["model"])
        self._responses: dict[str, dict[str, str]] = {normalize_question(r["question"]): r for r in data["responses"]}

    def _get(self, question: str) -> dict[str, str]:
        r = self._responses.get(normalize_question(question))
        if r is None:
            raise ModelUnavailable(f"no recorded response for question {question!r}")
        return r

    def draft_sql(self, question: str, context: SchemaContext) -> Draft:
        return parse_draft(self._get(question)["draft"])

    def write_answer(self, question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        return self._get(question).get("answer", "")


class ReferenceModel:
    """Drafts the hand-written reference SQL; answers with an empty paragraph (so the fallback is used)."""

    name = "reference"

    def __init__(self, reference: Mapping[str, str]) -> None:
        self._sql = {normalize_question(q): s for q, s in reference.items()}

    def draft_sql(self, question: str, context: SchemaContext) -> Draft:
        sql = self._sql.get(normalize_question(question))
        if sql is None:
            return Draft(raw="", sql=None, refusal="no reference SQL for this question")
        return Draft(raw=sql, sql=sql, refusal=None)

    def write_answer(self, question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        return ""


class AnthropicModel:
    """Live adapter for the Anthropic Messages API. Optional; never used by tests, CI or ``make eval``.

    ``client`` is injectable so request building can be tested without a network or key.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        client: Any = None,
        max_tokens: int = 1024,
    ) -> None:
        self.model = model or os.environ.get("ROLLUP_LLM_MODEL", "")
        if not self.model:
            raise ModelUnavailable("set ROLLUP_LLM_MODEL (or pass model=) to the model id to call")
        if client is None:
            key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            if not key:
                raise ModelUnavailable("set ANTHROPIC_API_KEY to use the live model")
            try:
                import anthropic
            except ImportError as e:  # pragma: no cover - depends on the optional extra
                raise ModelUnavailable("install the live extra: pip install -e '.[live]'") from e
            client = anthropic.Anthropic(api_key=key)
        self._client = client
        self.max_tokens = max_tokens
        self.name = f"anthropic:{self.model}"

    def _complete(self, system: str, user: str) -> str:
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            raise ModelUnavailable(f"model call failed: {type(e).__name__}") from e
        return "".join(getattr(b, "text", "") for b in getattr(resp, "content", []) if getattr(b, "type", "") == "text")

    def draft_sql(self, question: str, context: SchemaContext) -> Draft:
        return parse_draft(self._complete(*build_sql_prompt(question, context)))

    def write_answer(self, question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        return self._complete(*build_answer_prompt(question, sql, columns, rows)).strip()
