"""Unit tests for the SQL guards (G1-G5). No database needed."""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp

from rollup.guards import DEFAULT_MAX_ROWS, MART_TABLES, GuardViolation, check_sql


def refused(sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> str:
    with pytest.raises(GuardViolation) as info:
        check_sql(sql, max_rows=max_rows)
    return info.value.code


def limit_of(sql: str) -> int | None:
    tree = sqlglot.parse_one(sql, read="duckdb")
    limit = tree.args.get("limit")
    if limit is None:
        return None
    assert isinstance(limit, exp.Limit)
    return int(limit.expression.this)


# RU-01: non-SELECT statements --------------------------------------------------------------------------

NON_SELECT = [
    "INSERT INTO marts.fct_spend VALUES (1)",
    "insert into marts.dim_channel select * from marts.dim_channel",
    "UPDATE marts.fct_spend SET spend_usd = 0",
    "DELETE FROM marts.fct_spend",
    "DROP TABLE marts.fct_spend",
    "drop schema marts cascade",
    "CREATE TABLE x AS SELECT 1",
    "create or replace view marts.v as select 1",
    "CREATE MACRO m(a) AS a",
    "ALTER TABLE marts.fct_spend ADD COLUMN x INT",
    "TRUNCATE marts.fct_spend",
    "MERGE INTO marts.fct_spend t USING marts.fct_spend s ON t.spend_id = s.spend_id WHEN MATCHED THEN DELETE",
    "COPY marts.fct_spend TO '/tmp/out.csv'",
    "COPY (SELECT 1) TO '/tmp/out.parquet' (FORMAT parquet)",
    "EXPORT DATABASE '/tmp/dump'",
    "ATTACH '/tmp/other.duckdb' AS other",
    "DETACH other",
    "PRAGMA database_list",
    "PRAGMA enable_profiling",
    "SET enable_external_access = true",
    "SET memory_limit = '100GB'",
    "RESET ALL",
    "INSTALL httpfs",
    "LOAD httpfs",
    "CALL pragma_version()",
    "USE marts",
    "BEGIN TRANSACTION",
    "COMMIT",
    "CHECKPOINT",
    "VACUUM",
    "DESCRIBE marts.fct_spend",
    "SHOW TABLES",
    "SUMMARIZE marts.fct_spend",
    "EXPLAIN SELECT 1",
    "PREPARE p AS SELECT 1",
    "EXECUTE p",
    "SELECT 1; DROP TABLE marts.fct_spend",
    "SELECT 1; SELECT 2",
    "select channel_key from marts.dim_channel; delete from marts.dim_channel",
    "WITH x AS (INSERT INTO marts.dim_channel VALUES ('a') RETURNING *) SELECT channel_key FROM x",
    "WITH x AS (DELETE FROM marts.dim_channel RETURNING *) SELECT channel_key FROM x",
    "SELECT channel_key INTO new_table FROM marts.dim_channel",
    "SELECT spend_usd FROM marts.fct_spend WHERE spend_id = ?",
    "SELECT spend_usd FROM marts.fct_spend WHERE spend_id = $1",
]


@pytest.mark.parametrize("sql", NON_SELECT)
def test_non_select_refused(sql: str) -> None:
    assert refused(sql) in {"not_select", "multiple_statements", "parse_error", "table_not_allowed"}


@pytest.mark.parametrize("sql", ["", "   ", "-- just a comment", ";", "/* */ ;"])
def test_empty_refused(sql: str) -> None:
    assert refused(sql) in {"empty", "parse_error", "not_select"}


def test_too_long_refused() -> None:
    assert refused("SELECT 1 " + " " * 20_000) == "too_long"


def test_garbage_refused() -> None:
    assert refused("SELEC channel_key FROM marts.dim_channel") in {"parse_error", "not_select"}


# RU-02: allowlist -----------------------------------------------------------------------------------------

OUTSIDE_ALLOWLIST = [
    "SELECT * FROM staging.stg_ad_spend",
    "SELECT lead_id FROM intermediate.int_leads_stitched",
    "SELECT table_name FROM information_schema.tables",
    "SELECT table_name FROM information_schema.columns",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT * FROM main.marts.fct_spend",
    "SELECT * FROM rollup.marts.dim_channel",
    "SELECT * FROM system.main.duckdb_tables",
    "SELECT * FROM marts.not_a_table",
    "SELECT * FROM stg_ad_spend",
    "SELECT * FROM 'data/raw/ad_spend.parquet'",
    "SELECT * FROM '/etc/passwd'",
    'SELECT * FROM "data/raw/crm_contacts.parquet"',
    "SELECT channel_key FROM marts.dim_channel WHERE channel_key IN "
    "(SELECT lead_id FROM intermediate.int_leads_stitched)",
    "SELECT (SELECT max(lead_id) FROM intermediate.int_leads_stitched) AS x",
    "SELECT channel_key FROM marts.dim_channel UNION ALL SELECT table_name FROM information_schema.tables",
    "WITH t AS (SELECT * FROM staging.stg_crm_contacts) SELECT * FROM t",
    "SELECT d.channel_key FROM marts.dim_channel d JOIN intermediate.int_campaign_map m ON true",
    "SELECT * FROM marts.dim_channel, LATERAL (SELECT * FROM staging.stg_campaigns) s",
    # CTE named t is only visible inside the derived table; the outer t is a real (non-allowlisted) table
    "SELECT * FROM (WITH t AS (SELECT 1 AS a) SELECT a FROM t) s, t",
    "SELECT * FROM duckdb_tables",
    # a derived table's alias is not a CTE: the real table "s" must still be checked (hypothesis found this)
    'SELECT count(*) FROM (SELECT 1 AS a) s, "s"',
    'SELECT count(*) FROM (WITH s AS (SELECT 1 AS a) SELECT a FROM s) s, "s"',
]


@pytest.mark.parametrize("sql", OUTSIDE_ALLOWLIST)
def test_outside_allowlist_refused(sql: str) -> None:
    assert refused(sql) == "table_not_allowed"


TABLE_FUNCTIONS = [
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_csv_auto('data/raw/x.csv')",
    "SELECT * FROM read_parquet('data/raw/ad_spend.parquet')",
    "SELECT * FROM read_json('x.json')",
    "SELECT * FROM read_text('/etc/hostname')",
    "SELECT * FROM query('SELECT * FROM staging.stg_ad_spend')",
    "SELECT * FROM query_table('staging.stg_ad_spend')",
    "SELECT * FROM glob('*')",
    "SELECT * FROM duckdb_tables()",
    "SELECT * FROM duckdb_settings()",
    "SELECT * FROM pragma_table_info('marts.fct_spend')",
    "SELECT * FROM range(10)",
    "SELECT * FROM parquet_metadata('x.parquet')",
]


@pytest.mark.parametrize("sql", TABLE_FUNCTIONS)
def test_table_functions_refused(sql: str) -> None:
    assert refused(sql) in {"table_function", "function_not_allowed"}


SCALAR_FUNCTIONS = [
    "SELECT read_text('/etc/hostname') AS t",
    "SELECT getenv('HOME') AS h",
    "SELECT current_setting('memory_limit') AS m",
    "SELECT getvariable('x') AS v",
    "SELECT json_execute_serialized_sql('{}') AS j",
    "SELECT channel_key FROM marts.dim_channel WHERE channel_key IN (SELECT name FROM duckdb_settings())",
    "SELECT channel_key, (SELECT count(*) FROM query('select 1')) AS n FROM marts.dim_channel",
]


@pytest.mark.parametrize("sql", SCALAR_FUNCTIONS)
def test_system_functions_refused(sql: str) -> None:
    assert refused(sql) in {"function_not_allowed", "table_function"}


ALLOWED = [
    "SELECT channel_key, channel_name FROM marts.dim_channel",
    "SELECT * FROM marts.dim_channel",
    "SELECT * FROM marts.dim_campaign",
    "SELECT * FROM marts.mart_cac_by_channel",
    "SELECT * FROM marts.mart_funnel_weekly",
    "select channel_key from MARTS.DIM_CHANNEL",
    'SELECT channel_key FROM "marts"."dim_channel"',
    "SELECT spend_date, sum(spend_usd) AS s FROM marts.fct_spend GROUP BY 1 ORDER BY 1",
    "SELECT count(*) FROM marts.fct_spend",
    "SELECT count(*) AS n, sum(spend_usd) AS s FROM marts.fct_spend",
    "WITH t AS (SELECT channel_key, spend_usd FROM marts.fct_spend) "
    "SELECT channel_key, sum(spend_usd) FROM t GROUP BY 1",
    "WITH fct_spend AS (SELECT 1 AS a) SELECT * FROM fct_spend",
    "SELECT channel_key FROM marts.dim_channel UNION SELECT channel_key FROM marts.fct_spend",
    "SELECT c.channel_name, sum(s.spend_usd) FROM marts.fct_spend s "
    "JOIN marts.dim_channel c USING (channel_key) GROUP BY 1",
    "SELECT 1 AS one",
    "SELECT x FROM (VALUES (1), (2)) AS v(x)",
    "SELECT unnest([1, 2, 3]) AS x",
    "SELECT d.* FROM marts.dim_channel d",
    "FROM marts.dim_channel SELECT channel_key",
    "SELECT channel_key, row_number() OVER (ORDER BY channel_key) AS rn FROM marts.dim_channel",
    "SELECT date_trunc('month', spend_date) AS m, sum(spend_usd) FROM marts.fct_spend GROUP BY ALL",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql: str) -> None:
    check_sql(sql)


def test_reports_tables_read() -> None:
    g = check_sql(
        "WITH t AS (SELECT channel_key FROM marts.fct_spend) "
        "SELECT c.channel_name FROM t JOIN marts.dim_channel c USING (channel_key)"
    )
    assert g.tables == {"fct_spend", "dim_channel"}


def test_unqualified_mart_names_are_pinned_to_marts() -> None:
    g = check_sql("SELECT channel_key FROM dim_channel")
    assert "marts.dim_channel" in g.sql.lower()
    assert g.tables == {"dim_channel"}


def test_cte_named_like_a_mart_is_not_rewritten() -> None:
    g = check_sql("WITH dim_channel AS (SELECT 'x' AS channel_key) SELECT channel_key FROM dim_channel")
    assert "marts.dim_channel" not in g.sql.lower()
    assert g.tables == frozenset()


def test_executed_sql_is_regenerated_without_smuggled_statements() -> None:
    g = check_sql("SELECT channel_key FROM marts.dim_channel /* ; DROP TABLE marts.dim_channel */")
    reparsed = [s for s in sqlglot.parse(g.sql, read="duckdb") if s is not None]
    assert len(reparsed) == 1 and isinstance(reparsed[0], exp.Select)


def test_allowlist_is_marts_only() -> None:
    assert len(MART_TABLES) == 7
    assert all(t.startswith(("fct_", "dim_", "mart_")) for t in MART_TABLES)


# G4: no * on fact tables ---------------------------------------------------------------------------------

STAR_ON_FACT = [
    "SELECT * FROM marts.fct_spend",
    "SELECT * FROM marts.fct_pipeline",
    "SELECT * FROM marts.fct_touches",
    "FROM marts.fct_spend",
    "SELECT s.* FROM marts.fct_spend s",
    "SELECT * EXCLUDE (spend_usd) FROM marts.fct_spend",
    "SELECT * REPLACE (spend_usd * 2 AS spend_usd) FROM marts.fct_spend",
    "SELECT COLUMNS(*) FROM marts.fct_spend",
    "SELECT COLUMNS('spend_.*') FROM marts.fct_spend",
    "SELECT c.*, s.spend_usd FROM marts.fct_spend s JOIN marts.dim_channel c USING (channel_key)",
    "SELECT * FROM (SELECT * FROM marts.fct_pipeline) p",
    "WITH p AS (SELECT * FROM marts.fct_pipeline) SELECT opportunity_id FROM p",
    "SELECT * FROM marts.dim_channel WHERE channel_key IN (SELECT channel_key FROM marts.fct_spend)",
]


@pytest.mark.parametrize("sql", STAR_ON_FACT)
def test_star_on_fact_refused(sql: str) -> None:
    assert refused(sql) == "star_on_fact_table"


# G5: row limit -------------------------------------------------------------------------------------------


def test_limit_injected_when_missing() -> None:
    g = check_sql("SELECT channel_key FROM marts.dim_channel", max_rows=100)
    assert limit_of(g.sql) == 101
    assert g.row_cap == 100


def test_larger_limit_is_capped() -> None:
    g = check_sql("SELECT spend_id FROM marts.fct_spend LIMIT 5000", max_rows=100)
    assert limit_of(g.sql) == 101


def test_smaller_limit_kept() -> None:
    g = check_sql("SELECT spend_id FROM marts.fct_spend ORDER BY spend_id LIMIT 7 OFFSET 3", max_rows=100)
    assert limit_of(g.sql) == 7
    assert "OFFSET 3" in g.sql


def test_limit_on_set_operation_applies_to_whole_query() -> None:
    g = check_sql("SELECT channel_key FROM marts.dim_channel UNION ALL SELECT channel_key FROM marts.dim_channel")
    tree = sqlglot.parse_one(g.sql, read="duckdb")
    assert isinstance(tree, exp.Union)
    assert tree.args.get("limit") is not None


def test_inner_limit_does_not_replace_outer_cap() -> None:
    g = check_sql("SELECT spend_id FROM (SELECT spend_id FROM marts.fct_spend LIMIT 99999) t", max_rows=10)
    assert limit_of(g.sql) == 11


def test_default_cap() -> None:
    assert check_sql("SELECT 1 AS x").row_cap == DEFAULT_MAX_ROWS == 1000


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT spend_id FROM marts.fct_spend LIMIT (SELECT 10)",
        "SELECT spend_id FROM marts.fct_spend LIMIT ALL",
        "SELECT spend_id FROM marts.fct_spend LIMIT 50%",
        "SELECT spend_id FROM marts.fct_spend LIMIT 10 PERCENT",
        "SELECT spend_id FROM marts.fct_spend FETCH FIRST 5 ROWS ONLY",
        "SELECT spend_id FROM marts.fct_spend LIMIT 1 + 1",
    ],
)
def test_bad_limits_refused(sql: str) -> None:
    assert refused(sql) in {"bad_limit", "parse_error"}


def test_max_rows_must_be_positive() -> None:
    with pytest.raises(ValueError):
        check_sql("SELECT 1 AS x", max_rows=0)
