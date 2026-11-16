"""Golden-set eval: 40 questions, reference SQL, result-set equivalence, run file, pinned recorded-draft numbers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest

from rollup.eval import load_golden, load_refusals
from rollup.eval.run import RUN_SCHEMA, run_eval
from rollup.eval.run import main as eval_main
from rollup.guards import check_sql
from rollup.llm import DEFAULT_RECORDING, RecordedModel, ReferenceModel
from rollup.runner import execute_guarded, open_readonly
from rollup.schema_context import SchemaContext, load_context

GOLDEN = load_golden()
REFUSALS = load_refusals()
RECORDED = {r["id"]: r for r in json.loads(DEFAULT_RECORDING.read_text(encoding="utf-8"))["responses"]}

# What the recorded drafts score. These measure the pipeline on recorded drafts, not a live model (D-29).
PINNED_SUMMARY = {
    "golden_total": 40,
    "golden_equivalent": 27,
    "golden_status_counts": {"answered": 33, "query_error": 2, "refused_guard": 4, "refused_question": 1},
    "refusal_total": 8,
    "refusal_correct": 7,
    "refusal_status_counts": {"answered": 1, "query_error": 1, "refused_guard": 2, "refused_question": 4},
    "answers_shown": 34,
    "answers_from_model": 27,
    "answers_from_fallback": 7,
    "model_paragraphs_rejected_ru03": 7,
    "guard_refusals_by_code": {
        "multiple_statements": 1,
        "not_select": 1,
        "star_on_fact_table": 1,
        "table_function": 1,
        "table_not_allowed": 2,
    },
    "invariant_failures": 0,
}


def test_forty_golden_questions() -> None:
    assert len(GOLDEN) == 40
    assert len({g.id for g in GOLDEN}) == 40
    assert len({g.question for g in GOLDEN}) == 40
    assert all(g.question.endswith("?") for g in GOLDEN)


def test_refusal_set() -> None:
    assert len(REFUSALS) == 8
    assert not {r.question for r in REFUSALS} & {g.question for g in GOLDEN}


@pytest.mark.parametrize("g", GOLDEN, ids=lambda g: g.id)
def test_reference_sql_passes_guards_unchanged(g: Any) -> None:
    guarded = check_sql(g.sql)
    assert guarded.tables


def test_recorded_expectations_cover_every_bad_kind() -> None:
    statuses = {r["expect"]["status"] for r in RECORDED.values()}
    assert {"answered", "refused_guard", "query_error", "refused_question"} <= statuses
    gold = [r for r in RECORDED.values() if r["set"] == "golden"]
    assert any(r["expect"].get("equivalent") is False and r["expect"]["status"] == "answered" for r in gold)
    assert any(r["expect"].get("answer_source") == "fallback" for r in gold)


@pytest.fixture(scope="module")
def con(warehouse_db: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    c = open_readonly(warehouse_db)
    yield c
    c.close()


@pytest.fixture(scope="module")
def ctx(warehouse_db: Path, repo_root: Path) -> SchemaContext:
    return load_context(repo_root / "warehouse" / "target" / "manifest.json", warehouse_db)


@pytest.mark.warehouse
@pytest.mark.parametrize("g", GOLDEN, ids=lambda g: g.id)
def test_reference_sql_runs(con: Any, g: Any) -> None:
    r = execute_guarded(con, g.sql)
    assert r.rows and not r.truncated and r.elapsed_ms < 5000


@pytest.mark.warehouse
def test_reference_model_scores_forty_of_forty(con: Any, ctx: SchemaContext) -> None:
    run = run_eval(ReferenceModel({g.question: g.sql for g in GOLDEN}), con, ctx, GOLDEN, REFUSALS, drafts="reference")
    s = run["summary"]
    assert s["golden_equivalent"] == 40
    assert s["answers_from_fallback"] == 40  # ReferenceModel writes no paragraph
    assert s["refusal_correct"] == 8
    assert s["invariant_failures"] == 0


@pytest.fixture(scope="module")
def recorded_run(con: Any, ctx: SchemaContext) -> dict[str, Any]:
    return run_eval(RecordedModel(), con, ctx, GOLDEN, REFUSALS, drafts="recorded")


@pytest.mark.warehouse
def test_recorded_run_matches_pinned_summary(recorded_run: dict[str, Any]) -> None:
    s = recorded_run["summary"]
    assert {k: s[k] for k in PINNED_SUMMARY} == PINNED_SUMMARY
    assert s["golden_score"] == 0.675
    assert recorded_run["schema"] == RUN_SCHEMA
    assert "not a live model" in recorded_run["note"]


@pytest.mark.warehouse
def test_recorded_run_matches_each_expectation(recorded_run: dict[str, Any]) -> None:
    for item in recorded_run["items"]:
        expect = RECORDED[item["id"]]["expect"]
        got = {k: item.get(k) for k in expect}
        assert got == expect, item["id"]


@pytest.mark.warehouse
def test_every_guard_violating_draft_was_refused(recorded_run: dict[str, Any]) -> None:
    for item in recorded_run["items"]:
        sql = item["draft_sql"]
        if sql is None:
            continue
        try:
            check_sql(sql)
        except Exception:
            assert item["status"] == "refused_guard" and item["executed_sql"] is None, item["id"]


@pytest.mark.warehouse
def test_every_dishonest_paragraph_was_rejected(recorded_run: dict[str, Any]) -> None:
    rejected = [i for i in recorded_run["items"] if i["model_answer_violations"]]
    assert rejected
    for item in rejected:
        assert item["answer_source"] == "fallback"
        assert item["answer"] != item["model_answer"]


@pytest.mark.warehouse
def test_eval_cli_writes_run_file(tmp_path: Path, warehouse_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "run.json"
    assert eval_main(["--out", str(out), "--db", str(warehouse_db)]) == 0
    run = json.loads(out.read_text(encoding="utf-8"))
    assert run["summary"]["golden_equivalent"] == 27 and run["summary"]["db_unchanged"] is True
    assert len(run["items"]) == 48
    assert "not a live model" in capsys.readouterr().out


@pytest.mark.warehouse
def test_eval_cli_live_without_key_exits(tmp_path: Path, warehouse_db: Path) -> None:
    assert eval_main(["--model", "live", "--out", str(tmp_path / "x.json"), "--db", str(warehouse_db)]) == 2
    assert not (tmp_path / "x.json").exists()
