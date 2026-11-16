"""The ask pipeline: drafts go through the Phase 2 guards unchanged; answers obey RU-03; refusals show no numbers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import duckdb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import rollup.runner
from rollup.ask import AskResult, ask
from rollup.ask import main as ask_main
from rollup.guards import GuardedQuery, GuardViolation, check_sql
from rollup.llm import Draft, ModelUnavailable, parse_draft
from rollup.runner import open_readonly
from rollup.schema_context import SchemaContext, load_context
from rollup.validator import validate_answer

pytestmark = pytest.mark.warehouse

SPEND_SQL = "select platform, sum(spend_usd) as spend_usd from marts.fct_spend group by platform order by platform"


class FakeModel:
    name = "fake"

    def __init__(self, draft: str | Exception, answer: str | Exception = "") -> None:
        self.draft, self.answer = draft, answer

    def draft_sql(self, question: str, context: SchemaContext) -> Draft:
        if isinstance(self.draft, Exception):
            raise self.draft
        return parse_draft(self.draft)

    def write_answer(self, question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture(scope="module")
def con(warehouse_db: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    c = open_readonly(warehouse_db)
    yield c
    c.close()


@pytest.fixture(scope="module")
def ctx(warehouse_db: Path, repo_root: Path) -> SchemaContext:
    return load_context(repo_root / "warehouse" / "target" / "manifest.json", warehouse_db)


@pytest.fixture
def guard_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every SQL string the runner hands to the (unchanged) Phase 2 guards."""
    seen: list[str] = []
    real = check_sql

    def spy(sql: str, max_rows: int = 1000) -> GuardedQuery:
        seen.append(sql)
        return real(sql, max_rows=max_rows)

    monkeypatch.setattr(rollup.runner, "check_sql", spy)
    return seen


def assert_invariants(r: AskResult) -> None:
    if r.answered:
        assert validate_answer(r.answer, r.columns, r.rows).ok
        assert r.executed_sql is not None
    else:
        assert not re.search(r"\d", r.answer), r.answer
        assert not r.rows and r.executed_sql is None


def test_answered_with_model_paragraph(con: Any, ctx: SchemaContext, guard_calls: list[str]) -> None:
    rows = con.execute(SPEND_SQL).fetchall()
    answer = f"Google Ads spent ${rows[0][1]:,.2f}."
    r = ask("Spend by platform?", FakeModel(f"```sql\n{SPEND_SQL}\n```", answer), con, ctx)
    assert r.status == "answered" and r.answer_source == "model" and r.answer == answer
    assert guard_calls == [SPEND_SQL]
    assert r.executed_sql == check_sql(SPEND_SQL).sql  # what ran is what the guards produced
    assert_invariants(r)


def test_dishonest_paragraph_is_replaced_by_fallback(con: Any, ctx: SchemaContext) -> None:
    r = ask("Spend by platform?", FakeModel(SPEND_SQL, "All platforms together spent $1,024,548.35."), con, ctx)
    assert r.status == "answered" and r.answer_source == "fallback"
    assert r.validation is not None and not r.validation.ok
    assert r.model_answer == "All platforms together spent $1,024,548.35."
    assert "1,024,548.35" not in r.answer
    assert_invariants(r)


@pytest.mark.parametrize("answer", ["", ModelUnavailable("down")])
def test_missing_paragraph_uses_fallback(con: Any, ctx: SchemaContext, answer: str | Exception) -> None:
    r = ask("Spend by platform?", FakeModel(SPEND_SQL, answer), con, ctx)
    assert r.answer_source == "fallback"
    assert_invariants(r)


def test_model_refusal_is_the_refusal_path(con: Any, ctx: SchemaContext, guard_calls: list[str]) -> None:
    r = ask("What is our NPS?", FakeModel("REFUSE: no survey data"), con, ctx)
    assert r.status == "refused_question" and r.reason == "no survey data"
    assert guard_calls == []
    assert_invariants(r)


ATTACKS = [
    "delete from marts.fct_pipeline",
    "drop table marts.fct_spend",
    "update marts.dim_channel set is_paid = true",
    "insert into marts.dim_channel values ('x', 'x', 'paid', true)",
    "create table marts.x as select 1",
    "select 1 as one from marts.dim_channel; drop table marts.dim_channel",
    "attach 'evil.duckdb' as evil",
    "copy marts.fct_spend to 'out.csv'",
    "set enable_external_access = true",
    "pragma database_list",
    "select person_key from staging.stg_crm_contacts",
    "select lead_id from intermediate.int_leads_stitched",
    "select table_name from information_schema.tables",
    "select * from read_csv('data/raw/x.csv')",
    "select * from marts.fct_pipeline",
    "select p.* from marts.fct_pipeline p",
    "with x as (delete from marts.fct_spend returning spend_id) select spend_id from x",
    "select getenv('HOME') as h",
]


@pytest.mark.parametrize("sql", ATTACKS)
def test_guard_violating_drafts_never_execute(con: Any, ctx: SchemaContext, guard_calls: list[str], sql: str) -> None:
    with pytest.raises(GuardViolation) as direct:
        check_sql(sql)
    r = ask("Any question?", FakeModel(f"```sql\n{sql}\n```"), con, ctx)
    assert r.status == "refused_guard"
    assert r.guard_code == direct.value.code  # same refusal Phase 2 gives
    assert guard_calls == [sql]
    assert_invariants(r)


def test_attacks_leave_the_database_file_unchanged(warehouse_db: Path, ctx: SchemaContext) -> None:
    before = hashlib.sha256(warehouse_db.read_bytes()).hexdigest()
    c = open_readonly(warehouse_db)
    try:
        for sql in ATTACKS:
            assert ask("q?", FakeModel(sql), c, ctx).status == "refused_guard"
    finally:
        c.close()
    assert hashlib.sha256(warehouse_db.read_bytes()).hexdigest() == before


def test_query_error(con: Any, ctx: SchemaContext) -> None:
    r = ask("q?", FakeModel("select no_such_column from marts.dim_channel"), con, ctx)
    assert r.status == "query_error" and r.reason
    assert_invariants(r)


def test_timeout(con: Any, ctx: SchemaContext) -> None:
    heavy = "select count(*) as n from marts.fct_touches a, marts.fct_touches b, marts.fct_touches c"
    r = ask("q?", FakeModel(heavy), con, ctx, timeout_s=0.3)
    assert r.status == "timeout"
    assert_invariants(r)
    assert con.execute("select 1").fetchone() == (1,)  # connection still usable


def test_model_error(con: Any, ctx: SchemaContext) -> None:
    r = ask("q?", FakeModel(ModelUnavailable("no recording")), con, ctx)
    assert r.status == "model_error"
    assert_invariants(r)


def test_row_cap_applies_to_drafts(con: Any, ctx: SchemaContext) -> None:
    r = ask("q?", FakeModel("select touch_id from marts.fct_touches"), con, ctx, max_rows=10)
    assert r.status == "answered" and len(r.rows) == 10 and r.truncated
    assert_invariants(r)


@settings(max_examples=60)
@given(st.text(alphabet="0123456789$,.% abcQ-k", max_size=40))
def test_any_model_paragraph_yields_a_valid_shown_answer(warehouse_db: Path, text: str) -> None:
    c = open_readonly(warehouse_db)
    try:
        ctx = SchemaContext(tables=())
        r = ask("Spend by platform?", FakeModel(SPEND_SQL, text), c, ctx)
    finally:
        c.close()
    assert r.status == "answered"
    assert_invariants(r)


def test_cli_answers_a_recorded_question(capsys: pytest.CaptureFixture[str], warehouse_db: Path) -> None:
    code = ask_main(["Which five campaigns have the highest lifetime spend?", "--db", str(warehouse_db)])
    out = capsys.readouterr().out
    assert code == 0 and "status: answered" in out and "executed SQL" in out and "answer (model)" in out


def test_cli_unknown_question_is_a_model_error(capsys: pytest.CaptureFixture[str], warehouse_db: Path) -> None:
    assert ask_main(["Something nobody recorded?", "--db", str(warehouse_db)]) == 5
    assert "status: model_error" in capsys.readouterr().out


def test_cli_live_without_key_refuses_to_start(capsys: pytest.CaptureFixture[str], warehouse_db: Path) -> None:
    assert ask_main(["q?", "--model", "live", "--db", str(warehouse_db)]) == 5
    assert "live model unavailable" in capsys.readouterr().err
