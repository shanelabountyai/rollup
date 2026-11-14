"""The hand-written SQL library: every query passes the guards, runs under the timeout and reconciles."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest

from rollup.guards import check_sql
from rollup.queries import load_queries
from rollup.query import EXIT_OK, EXIT_REFUSED, main
from rollup.runner import QueryResult, run_sql

QUERIES = load_queries()


def oracle_one(db: Path, sql: str) -> Any:
    with duckdb.connect(str(db), read_only=True) as con:
        row = con.execute(sql).fetchone()
    assert row is not None
    return row[0]


def run(db: Path, name: str) -> QueryResult:
    return run_sql(QUERIES[name].sql, db_path=db)


def col(result: QueryResult, name: str) -> list[Any]:
    i = result.columns.index(name)
    return [r[i] for r in result.rows]


def test_library_has_twelve_questions() -> None:
    assert len(QUERIES) == 12
    assert all(q.question.endswith("?") for q in QUERIES.values())


@pytest.mark.parametrize("name", sorted(QUERIES))
def test_query_passes_guards(name: str) -> None:
    g = check_sql(QUERIES[name].sql)
    assert g.tables  # every hand-written query reads at least one mart


@pytest.mark.warehouse
@pytest.mark.parametrize("name", sorted(QUERIES))
def test_query_runs(warehouse_db: Path, name: str) -> None:
    result = run(warehouse_db, name)
    assert result.rows and not result.truncated
    assert result.elapsed_ms < 5000


@pytest.mark.warehouse
def test_spend_queries_reconcile(warehouse_db: Path) -> None:
    total = oracle_one(warehouse_db, "SELECT sum(spend_usd) FROM marts.fct_spend")
    assert sum(col(run(warehouse_db, "spend_by_channel_month"), "spend_usd")) == total
    assert sum(col(run(warehouse_db, "spend_by_platform"), "spend_usd")) == total
    paid_cac = oracle_one(warehouse_db, "SELECT sum(spend_usd) FROM marts.mart_cac_by_channel WHERE is_paid")
    assert sum(col(run(warehouse_db, "cac_by_channel_quarter"), "spend_usd")) == paid_cac == total


@pytest.mark.warehouse
def test_first_and_last_touch_totals_agree(warehouse_db: Path) -> None:
    """D-20: both credit models count every won deal and dollar exactly once."""
    r = run(warehouse_db, "first_vs_last_touch_wins")
    won = oracle_one(warehouse_db, "SELECT count(*) FROM marts.fct_pipeline WHERE is_won")
    revenue = oracle_one(warehouse_db, "SELECT sum(won_amount_usd) FROM marts.fct_pipeline")
    assert sum(col(r, "deals_won_first_touch")) == sum(col(r, "deals_won_last_touch")) == won
    assert sum(col(r, "won_revenue_first_touch_usd")) == sum(col(r, "won_revenue_last_touch_usd")) == revenue
    assert sum(col(run(warehouse_db, "funnel_conversion_by_channel"), "wins")) == won
    assert sum(col(run(warehouse_db, "win_rate_by_first_touch"), "won_opportunities")) == won
    assert sum(col(run(warehouse_db, "days_to_close_by_channel"), "won_deals")) == won


@pytest.mark.warehouse
def test_funnel_and_cac_agree_per_channel(warehouse_db: Path) -> None:
    funnel = run(warehouse_db, "first_vs_last_touch_wins")
    by_channel = dict(zip(col(funnel, "channel_key"), col(funnel, "deals_won_first_touch"), strict=True))
    cac = run(warehouse_db, "cac_by_channel_quarter")
    cac_totals: dict[str, int] = {}
    for ch, n in zip(col(cac, "channel_key"), col(cac, "new_customers"), strict=True):
        cac_totals[ch] = cac_totals.get(ch, 0) + int(n)
    for ch, n in cac_totals.items():
        assert by_channel[ch] == n


@pytest.mark.warehouse
def test_pipeline_and_people_counts_reconcile(warehouse_db: Path) -> None:
    opps = oracle_one(warehouse_db, "SELECT count(*) FROM marts.fct_pipeline")
    amount = oracle_one(warehouse_db, "SELECT sum(amount_usd) FROM marts.fct_pipeline")
    r = run(warehouse_db, "pipeline_by_stage")
    assert sum(col(r, "opportunities")) == opps
    assert sum(col(r, "amount_usd")) == amount
    people = oracle_one(warehouse_db, "SELECT count(DISTINCT person_key) FROM marts.fct_touches")
    assert sum(col(run(warehouse_db, "touches_per_converted_person"), "people")) == people
    campaigns = oracle_one(warehouse_db, "SELECT count(*) FROM marts.dim_campaign")
    assert len(run(warehouse_db, "paid_campaign_pipeline").rows) == campaigns


@pytest.mark.warehouse
def test_top_campaigns_sorted_and_renames_collapsed(warehouse_db: Path) -> None:
    r = run(warehouse_db, "top_campaigns_by_spend")
    assert len(r.rows) == 10
    spends = col(r, "lifetime_spend_usd")
    assert spends == sorted(spends, reverse=True)
    assert all(isinstance(v, Decimal | float | int) for v in spends)
    ids = col(r, "campaign_id")
    assert len(set(ids)) == len(ids)  # D4: a renamed campaign is one row, not two
    assert oracle_one(warehouse_db, "SELECT count(*) FROM marts.dim_campaign WHERE was_renamed") == 1


@pytest.mark.warehouse
def test_cli(warehouse_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--all", "--db", str(warehouse_db)]) == EXIT_OK
    assert main(["--name", "pipeline_by_stage", "--db", str(warehouse_db)]) == EXIT_OK
    assert main(["DROP TABLE marts.fct_spend", "--db", str(warehouse_db)]) == EXIT_REFUSED
    assert main(["SELECT * FROM staging.stg_ad_spend", "--db", str(warehouse_db)]) == EXIT_REFUSED
    out = capsys.readouterr().out
    assert "REFUSED [not_select]" in out and "REFUSED [table_not_allowed]" in out
    assert main(["--list"]) == EXIT_OK
