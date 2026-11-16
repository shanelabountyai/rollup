"""The drafting-model interface: parsing, prompts, recorded replay and the (never-called) live adapter."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from rollup.eval import load_golden, load_refusals
from rollup.llm import (
    DEFAULT_RECORDING,
    AnthropicModel,
    ModelUnavailable,
    RecordedModel,
    ReferenceModel,
    build_answer_prompt,
    build_sql_prompt,
    parse_draft,
)
from rollup.schema_context import ColumnInfo, SchemaContext, TableInfo

CTX = SchemaContext(
    tables=(
        TableInfo(
            name="fct_spend",
            description="Ad spend at campaign x day grain.",
            columns=(ColumnInfo("spend_usd", "Spend in USD.", "DECIMAL(12,2)"), ColumnInfo("channel_key", "Channel.")),
        ),
    )
)


@pytest.mark.parametrize(
    ("raw", "sql"),
    [
        ("```sql\nselect 1\n```", "select 1"),
        ("Here you go:\n```SQL\nselect 2;\n```\nThanks", "select 2;"),
        ("```\nselect 3\n```", "select 3"),
        ("select 4", "select 4"),
        ("  select 5  ", "select 5"),
    ],
)
def test_parse_draft_extracts_sql(raw: str, sql: str) -> None:
    d = parse_draft(raw)
    assert d.sql == sql and d.refusal is None and d.raw == raw


def test_parse_draft_refusals() -> None:
    assert parse_draft("REFUSE: no NPS data").refusal == "no NPS data"
    assert parse_draft("refuse:").refusal == "refused"
    assert parse_draft("```sql\n```").refusal == "model returned no SQL"
    assert parse_draft("").sql is None


def test_sql_prompt_carries_rules_and_schema() -> None:
    system, user = build_sql_prompt("What was spend?", CTX)
    assert "marts.fct_spend" in system and "spend_usd DECIMAL(12,2) -- Spend in USD." in system
    assert "Never use * on fct_* tables" in system and "REFUSE:" in system
    assert user == "Question: What was spend?"


def test_answer_prompt_shows_at_most_fifty_rows() -> None:
    rows = [(i,) for i in range(60)]
    _, user = build_answer_prompt("Q?", "select 1", ["n"], rows)
    assert "\n49\n" in user and "\n50\n" not in user and "(more rows not shown)" in user


def test_recording_covers_every_eval_question_once() -> None:
    data = json.loads(DEFAULT_RECORDING.read_text(encoding="utf-8"))
    ids = [r["id"] for r in data["responses"]]
    assert len(ids) == len(set(ids))
    expected = {g.id for g in load_golden()} | {r.id for r in load_refusals()}
    assert set(ids) == expected
    assert "Not captured from an API" in data["provenance"]


def test_recorded_model_replays_by_question_text() -> None:
    m = RecordedModel()
    g = load_golden()[0]
    d = m.draft_sql("  " + g.question.upper() + " ", CTX)  # whitespace and case insensitive
    assert d.sql is not None and "marts.fct_spend" in d.sql
    with pytest.raises(ModelUnavailable):
        m.draft_sql("A question nobody recorded?", CTX)


def test_reference_model_drafts_reference_sql() -> None:
    golden = load_golden()
    m = ReferenceModel({g.question: g.sql for g in golden})
    assert m.draft_sql(golden[3].question, CTX).sql == golden[3].sql
    assert m.draft_sql("unknown?", CTX).refusal is not None
    assert m.write_answer("q", "s", [], []) == ""


def test_live_adapter_needs_model_and_key_and_never_runs_in_tests() -> None:
    with pytest.raises(ModelUnavailable, match="ROLLUP_LLM_MODEL"):
        AnthropicModel()
    with pytest.raises(ModelUnavailable, match="ANTHROPIC_API_KEY"):
        AnthropicModel("some-model")


class FakeMessages:
    def __init__(self, text: str, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text, self.fail = text, fail

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("boom")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_live_adapter_builds_requests_with_an_injected_client() -> None:
    msgs = FakeMessages("```sql\nselect 1\n```")
    m = AnthropicModel("model-x", client=SimpleNamespace(messages=msgs))
    assert m.name == "anthropic:model-x"
    assert m.draft_sql("Q?", CTX).sql == "select 1"
    call = msgs.calls[0]
    assert call["model"] == "model-x" and call["messages"] == [{"role": "user", "content": "Question: Q?"}]
    assert "marts.fct_spend" in call["system"]


def test_live_adapter_wraps_client_errors() -> None:
    m = AnthropicModel("model-x", client=SimpleNamespace(messages=FakeMessages("", fail=True)))
    with pytest.raises(ModelUnavailable, match="RuntimeError"):
        m.draft_sql("Q?", CTX)


KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")


def test_no_api_key_in_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in [*root.glob("rollup/**/*"), *root.glob("tests/*"), *root.glob("scripts/*"), *root.glob("*.toml")]:
        if path.is_file() and path.suffix in {".py", ".json", ".sql", ".toml", ".md"}:
            assert not KEY_PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")), path
