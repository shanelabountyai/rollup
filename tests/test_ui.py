"""Query UI routes (Phase 4) on the recorded model, offline, through FastAPI's TestClient.

The UI only calls ``rollup.ask.ask``; these tests check that what the page shows is what ``ask`` decided: guard
refusals carry their code and reason and no numbers, RU-03 holds on the shown answer, a rejected model paragraph is
never rendered, and the chart type follows the result shape.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import rollup.runner
from rollup.ask import ask
from rollup.guards import GuardedQuery, check_sql
from rollup.llm import ModelUnavailable, RecordedModel
from rollup.runner import open_readonly
from rollup.schema_context import SchemaContext, load_context
from rollup.ui.app import create_app, recorded_questions, select_model
from rollup.validator import validate_answer

SPEND_BY_PLATFORM = "What was total ad spend by platform?"  # recorded paragraph invents a total -> RU-03 rejects it
MONTHLY_SPEND = "What was total paid spend each month, in date order?"
DELETE_Q = "Delete all closed-lost opportunities older than a year."
NPS_Q = "What is our NPS by customer segment?"
TOP_FIVE = "Which five campaigns have the highest lifetime spend?"  # model paragraph passes RU-03


def _tag(page: str, testid: str) -> str | None:
    """Inner HTML of the first element with this data-testid (enough for these flat templates)."""
    m = re.search(rf'<(\w+)[^>]*data-testid="{testid}"[^>]*>(.*?)</\1>', page, re.DOTALL)
    return None if m is None else m.group(2)


def _text(fragment: str | None) -> str:
    return "" if fragment is None else html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


# ---- unit: model selection (no warehouse) --------------------------------------------------------------------


def test_select_model_defaults_to_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROLLUP_UI_MODEL", raising=False)
    assert isinstance(select_model(), RecordedModel)
    assert isinstance(select_model("recorded"), RecordedModel)


def test_live_model_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest strips ANTHROPIC_API_KEY and ROLLUP_LLM_MODEL, so live must refuse rather than guess (D-41).
    with pytest.raises(ModelUnavailable):
        select_model("live")
    monkeypatch.setenv("ROLLUP_UI_MODEL", "live")
    with pytest.raises(ModelUnavailable):
        select_model()
    monkeypatch.setenv("ROLLUP_LLM_MODEL", "some-model")
    with pytest.raises(ModelUnavailable, match="ANTHROPIC_API_KEY"):
        select_model()


def test_unknown_model_choice_is_an_error() -> None:
    with pytest.raises(ValueError):
        select_model("gpt")


def test_recorded_questions_cover_both_sets() -> None:
    qs = recorded_questions()
    assert len(qs) == 48
    assert {q["set"] for q in qs} == {"golden", "refusal"}


def test_missing_warehouse_is_a_clear_503(tmp_path: Path) -> None:
    client = TestClient(create_app(RecordedModel(), db_path=tmp_path / "nope.duckdb"))
    r = client.post("/ask", data={"question": SPEND_BY_PLATFORM})
    assert r.status_code == 503
    assert "make build" in r.text


def test_empty_and_overlong_questions_are_rejected(tmp_path: Path) -> None:
    client = TestClient(create_app(RecordedModel(), db_path=tmp_path / "nope.duckdb"))
    assert client.post("/ask", data={"question": "   "}).status_code == 400
    assert client.post("/ask", data={"question": "x" * 501}).status_code == 400
    # htmx only swaps 2xx, so the partial carries the error with a 200
    r = client.post("/ask", data={"question": ""}, headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'data-testid="error"' in r.text


# ---- routes against the built warehouse ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(warehouse_db: Path, repo_root: Path) -> TestClient:
    app = create_app(
        RecordedModel(), db_path=warehouse_db, manifest_path=repo_root / "warehouse" / "target" / "manifest.json"
    )
    return TestClient(app)


@pytest.fixture(scope="module")
def con(warehouse_db: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    c = open_readonly(warehouse_db)
    yield c
    c.close()


@pytest.fixture(scope="module")
def ctx(warehouse_db: Path, repo_root: Path) -> SchemaContext:
    return load_context(repo_root / "warehouse" / "target" / "manifest.json", warehouse_db)


def _ask(client: TestClient, q: str, *, htmx: bool = True) -> str:
    r = client.post("/ask", data={"question": q}, headers={"HX-Request": "true"} if htmx else {})
    assert r.status_code == 200
    return r.text


@pytest.mark.warehouse
def test_index_renders_with_vendored_htmx(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert '<script src="/static/htmx.min.js">' in r.text
    assert "recorded" in r.text and SPEND_BY_PLATFORM in r.text
    js = client.get("/static/htmx.min.js")
    assert js.status_code == 200 and "htmx" in js.text[:2000]
    assert client.get("/healthz").json()["db_exists"] is True


@pytest.mark.warehouse
def test_answered_question_shows_every_step(
    client: TestClient, con: duckdb.DuckDBPyConnection, ctx: SchemaContext
) -> None:
    expected = ask(TOP_FIVE, RecordedModel(), con, ctx)
    assert expected.status == "answered" and expected.answer_source == "model"
    page = _ask(client, TOP_FIVE)
    assert 'data-status="answered"' in page
    assert _text(_tag(page, "draft-sql")) == expected.draft_sql
    assert _text(_tag(page, "guard")) == "passed"
    assert _text(_tag(page, "executed-sql")) == expected.executed_sql
    assert _text(_tag(page, "answer")) == expected.answer
    assert 'data-testid="ru03-rejected"' not in page
    table = _tag(page, "result-table") or ""
    assert table.count("<tr>") == len(expected.rows) + 1  # header + rows
    assert 'data-chart="bar"' in page and "<svg" in page


@pytest.mark.warehouse
def test_full_page_without_htmx_has_the_same_result(client: TestClient) -> None:
    page = _ask(client, TOP_FIVE, htmx=False)
    assert page.lstrip().lower().startswith("<!doctype html>")
    assert 'data-status="answered"' in page and 'data-testid="result-table"' in page


@pytest.mark.warehouse
def test_guard_refusal_shows_code_and_reason_and_no_numbers(client: TestClient) -> None:
    page = _ask(client, DELETE_Q)
    assert 'data-status="refused_guard"' in page
    assert _text(_tag(page, "guard")) == "refused"
    assert _text(_tag(page, "guard-code")) == "not_select"
    assert _text(_tag(page, "reason"))
    assert _text(_tag(page, "draft-sql")).lower().startswith("delete")
    assert "executed-sql" not in page and "result-table" not in page and "<svg" not in page
    assert not re.search(r"\d", _text(_tag(page, "answer")))


@pytest.mark.warehouse
def test_model_refusal_and_unknown_question(client: TestClient) -> None:
    page = _ask(client, NPS_Q)
    assert 'data-status="refused_question"' in page
    assert _text(_tag(page, "guard")) == "not reached"
    assert not re.search(r"\d", _text(_tag(page, "answer")))
    page = _ask(client, "Which coupon code drove the most signups?")  # nothing recorded for it
    assert 'data-status="model_error"' in page
    assert "result-table" not in page


@pytest.mark.warehouse
def test_ru03_rejected_paragraph_is_never_rendered(
    client: TestClient, con: duckdb.DuckDBPyConnection, ctx: SchemaContext
) -> None:
    r = ask(SPEND_BY_PLATFORM, RecordedModel(), con, ctx)
    assert r.answer_source == "fallback" and r.validation is not None and not r.validation.ok
    assert r.model_answer
    page = _ask(client, SPEND_BY_PLATFORM)
    assert 'data-testid="ru03-rejected"' in page
    shown = _text(_tag(page, "answer"))
    assert shown == r.answer
    assert validate_answer(shown, r.columns, r.rows, r.question).ok
    plain = html.unescape(page)
    assert r.model_answer not in plain
    for v in r.validation.violations:
        assert v not in plain
    # the invented total (a sum of the three platforms) appears nowhere on the page
    invented = re.findall(r"'([^']+)'", " ".join(r.validation.violations))
    assert invented
    for token in invented:
        assert token not in plain


@pytest.mark.warehouse
def test_chart_type_follows_result_shape(client: TestClient) -> None:
    assert 'data-chart="line"' in _ask(client, MONTHLY_SPEND)
    assert 'data-chart="bar"' in _ask(client, SPEND_BY_PLATFORM)
    one_row = _ask(client, "What is the total value of open (not closed) pipeline?")
    assert 'data-chart="none"' in one_row and "<svg" not in one_row


@pytest.mark.warehouse
def test_every_recorded_question_through_the_ui(
    client: TestClient,
    con: duckdb.DuckDBPyConnection,
    ctx: SchemaContext,
    warehouse_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All 48 recorded questions: every draft goes through check_sql, RU-03 holds on what is shown, DB unchanged."""
    before = hashlib.sha256(warehouse_db.read_bytes()).hexdigest()
    seen: list[str] = []

    def spy(sql: str, *, max_rows: int = 1000) -> GuardedQuery:
        seen.append(sql)
        return check_sql(sql, max_rows=max_rows)

    monkeypatch.setattr(rollup.runner, "check_sql", spy)
    questions = [q["question"] for q in recorded_questions()]
    drafted = 0
    for q in questions:
        expected = ask(q, RecordedModel(), con, ctx)  # runs through the spy too
        n_before = len(seen)
        page = _ask(client, q)
        assert f'data-status="{expected.status}"' in page, q
        shown = _text(_tag(page, "answer"))
        assert shown == expected.answer, q
        if expected.draft_sql is not None:
            drafted += 1
            assert len(seen) == n_before + 1, f"UI ran a draft without check_sql: {q}"
            assert seen[-1] == expected.draft_sql
        if expected.answered:
            assert validate_answer(shown, expected.columns, expected.rows, q).ok, q
            if expected.model_answer and expected.validation and not expected.validation.ok:
                assert expected.model_answer not in html.unescape(page), q
        else:
            assert not re.search(r"\d", shown), q
            assert "result-table" not in page, q
    assert drafted > 40
    assert hashlib.sha256(warehouse_db.read_bytes()).hexdigest() == before


def test_ui_module_runs_no_sql_of_its_own() -> None:
    """The app reaches DuckDB only through open_readonly + ask (which guards): no duckdb import, no execute calls."""
    import ast

    src = (Path(rollup.runner.__file__).parent / "ui" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    assert not any(name == "duckdb" or name.startswith("duckdb.") for name in imported)
    assert {n for n in imported if n.startswith("rollup.runner.")} <= {
        "rollup.runner.open_readonly",
        "rollup.runner.default_db_path",
    }
    assert "rollup.ask.ask" in imported
    calls = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not calls & {"execute", "executemany", "sql", "query", "run_sql", "execute_guarded", "check_sql"}
