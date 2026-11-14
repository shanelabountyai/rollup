"""Runner tests against the built warehouse: read-only connection (G6), timeout (G7), row cap, RU-01, RU-02."""

from __future__ import annotations

import contextlib
import hashlib
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest
import sqlglot
from sqlglot import exp

from rollup.guards import MART_TABLES, GuardViolation
from rollup.queries import load_queries
from rollup.runner import (
    DEFAULT_TIMEOUT_S,
    QueryError,
    QueryTimeout,
    execute_guarded,
    open_readonly,
    run_sql,
)
from tests.test_guards import NON_SELECT, OUTSIDE_ALLOWLIST, SCALAR_FUNCTIONS, STAR_ON_FACT, TABLE_FUNCTIONS

pytestmark = pytest.mark.warehouse

SLOW_SQL = (
    "SELECT sum(a.linear_weight * b.linear_weight) AS x "
    "FROM marts.fct_touches a, marts.fct_touches b, marts.fct_spend c"
)
ATTACKS = NON_SELECT + OUTSIDE_ALLOWLIST + TABLE_FUNCTIONS + SCALAR_FUNCTIONS + STAR_ON_FACT


def oracle(db: Path, sql: str) -> list[tuple[Any, ...]]:
    """Direct read (no guards) used only as the test oracle."""
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(sql).fetchall()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# G6: the connection itself ---------------------------------------------------------------------------------


def test_connection_is_read_only(warehouse_db: Path) -> None:
    con = open_readonly(warehouse_db)
    try:
        assert con.execute("SELECT current_setting('access_mode')").fetchone() == ("read_only",)
        for stmt in [
            "CREATE TABLE marts.x AS SELECT 1",
            "DELETE FROM marts.dim_channel",
            "DROP TABLE marts.dim_channel",
            "INSERT INTO marts.dim_channel (channel_key) VALUES ('x')",
        ]:
            with pytest.raises(duckdb.Error):
                con.execute(stmt)
    finally:
        con.close()


@pytest.mark.parametrize(
    "stmt",
    [
        "SET enable_external_access = true",
        "SET lock_configuration = false",
        "SET memory_limit = '64GB'",
    ],
)
def test_connection_configuration_is_locked(warehouse_db: Path, stmt: str) -> None:
    con = open_readonly(warehouse_db)
    try:
        with pytest.raises(duckdb.Error):
            con.execute(stmt)
    finally:
        con.close()


@pytest.mark.parametrize(
    "stmt",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_text('/etc/hostname')",
        "SELECT * FROM staging.stg_ad_spend LIMIT 1",  # staging views read raw Parquet
        "COPY (SELECT 1) TO '/tmp/rollup_should_not_exist.csv'",
        "INSTALL httpfs",
    ],
)
def test_connection_has_no_file_or_extension_access(warehouse_db: Path, stmt: str) -> None:
    con = open_readonly(warehouse_db)
    try:
        with pytest.raises(duckdb.Error):
            con.execute(stmt)
    finally:
        con.close()
    assert not Path("/tmp/rollup_should_not_exist.csv").exists()


def test_missing_database_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_readonly(tmp_path / "nope.duckdb")


# RU-02 against the real catalog ----------------------------------------------------------------------------


def _all_relations(db: Path) -> list[tuple[str, str]]:
    return [
        (s, t) for s, t in oracle(db, "SELECT table_schema, table_name FROM information_schema.tables ORDER BY 1, 2")
    ] + [("information_schema", "tables"), ("information_schema", "columns"), ("pg_catalog", "pg_class")]


def test_allowlist_matches_marts(warehouse_db: Path, repo_root: Path) -> None:
    in_db = {t for s, t in _all_relations(warehouse_db) if s == "marts"}
    in_dbt = {p.stem for p in (repo_root / "warehouse" / "models" / "marts").glob("*.sql")}
    assert in_db == in_dbt == MART_TABLES


def test_ru02_every_non_mart_relation_refused(warehouse_db: Path) -> None:
    others = [(s, t) for s, t in _all_relations(warehouse_db) if s != "marts"]
    assert len(others) >= 15  # staging + intermediate + system catalogs
    for schema, table in others:
        assert table not in MART_TABLES  # so the bare-name variant below must be refused too
        for sql in [
            f'SELECT count(*) FROM {schema}."{table}"',
            f'SELECT count(*) FROM marts.dim_channel WHERE EXISTS (SELECT 1 FROM {schema}."{table}")',
            f'SELECT count(*) FROM "{table}"',
        ]:
            with pytest.raises(GuardViolation) as info:
                run_sql(sql, db_path=warehouse_db)
            assert info.value.code == "table_not_allowed", sql


@pytest.mark.parametrize("table", sorted(MART_TABLES))
def test_every_mart_is_readable(warehouse_db: Path, table: str) -> None:
    result = run_sql(f"SELECT count(*) AS n FROM marts.{table}", db_path=warehouse_db)
    assert result.rows == oracle(warehouse_db, f"SELECT count(*) FROM marts.{table}")
    assert result.rows[0][0] > 0


# RU-01: only SELECTs reach DuckDB --------------------------------------------------------------------------


class RecordingConnection:
    """Wraps a DuckDB connection and records every statement executed through it."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con
        self.executed: list[str] = []

    def execute(self, sql: str, *args: Any) -> Any:
        self.executed.append(sql)
        return self._con.execute(sql, *args)

    def interrupt(self) -> None:
        self._con.interrupt()


def test_ru01_only_single_selects_are_executed(warehouse_db: Path) -> None:
    con = open_readonly(warehouse_db)
    rec = RecordingConnection(con)
    try:
        queries = [q.sql for q in load_queries().values()]
        for sql in queries + ATTACKS:
            with contextlib.suppress(GuardViolation):
                execute_guarded(rec, sql)  # type: ignore[arg-type]
    finally:
        con.close()
    assert len(rec.executed) == len(queries)  # every attack was refused before execution
    for sql in rec.executed:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
        assert len(statements) == 1 and isinstance(statements[0], exp.Select | exp.SetOperation), sql


def test_ru01_attack_corpus_leaves_database_unchanged(warehouse_db: Path, tmp_path: Path) -> None:
    db = tmp_path / "copy.duckdb"
    shutil.copyfile(warehouse_db, db)
    before = sha256(db)
    refused = 0
    for sql in ATTACKS:
        try:
            run_sql(sql, db_path=db)
        except GuardViolation:
            refused += 1
    assert refused == len(ATTACKS)
    for q in load_queries().values():
        run_sql(q.sql, db_path=db)
    assert sha256(db) == before


# G5: row cap -----------------------------------------------------------------------------------------------


def test_row_cap_truncates_and_flags(warehouse_db: Path) -> None:
    result = run_sql("SELECT spend_id FROM marts.fct_spend ORDER BY spend_id", db_path=warehouse_db, max_rows=10)
    assert len(result.rows) == 10 and result.truncated
    assert "LIMIT 11" in result.sql


def test_row_cap_not_flagged_when_all_rows_fit(warehouse_db: Path) -> None:
    result = run_sql("SELECT channel_key FROM marts.dim_channel", db_path=warehouse_db, max_rows=6)
    assert len(result.rows) == 6 and not result.truncated
    result = run_sql("SELECT spend_id FROM marts.fct_spend LIMIT 10", db_path=warehouse_db, max_rows=10)
    assert len(result.rows) == 10 and not result.truncated


def test_default_row_cap_is_1000(warehouse_db: Path) -> None:
    result = run_sql("SELECT spend_id FROM marts.fct_spend", db_path=warehouse_db)
    assert len(result.rows) == 1000 and result.truncated


# G7: timeout -----------------------------------------------------------------------------------------------


def test_default_timeout_is_five_seconds() -> None:
    assert DEFAULT_TIMEOUT_S == 5.0
    assert run_sql.__kwdefaults__ is not None and run_sql.__kwdefaults__["timeout_s"] == 5.0


def test_slow_query_is_interrupted(warehouse_db: Path) -> None:
    con = open_readonly(warehouse_db)
    try:
        with pytest.raises(QueryTimeout):
            execute_guarded(con, SLOW_SQL, timeout_s=0.5)
        # The connection is still usable after an interrupt.
        assert execute_guarded(con, "SELECT count(*) AS n FROM marts.dim_channel").rows == [(6,)]
    finally:
        con.close()


def test_slow_query_hits_default_timeout(warehouse_db: Path) -> None:
    import time

    started = time.perf_counter()
    with pytest.raises(QueryTimeout):
        run_sql(SLOW_SQL, db_path=warehouse_db)
    assert 4.5 <= time.perf_counter() - started < 15


# Results ---------------------------------------------------------------------------------------------------


def test_results_match_direct_read(warehouse_db: Path) -> None:
    sql = "SELECT channel_key, sum(spend_usd) AS s FROM marts.fct_spend GROUP BY 1 ORDER BY 1"
    result = run_sql(sql, db_path=warehouse_db)
    assert result.columns == ["channel_key", "s"]
    assert result.rows == oracle(warehouse_db, sql)


def test_duckdb_errors_are_wrapped(warehouse_db: Path) -> None:
    with pytest.raises(QueryError):
        run_sql("SELECT no_such_column FROM marts.dim_channel", db_path=warehouse_db)


def test_guard_runs_before_connecting(tmp_path: Path) -> None:
    # A refused query never needs (or opens) the database.
    with pytest.raises(GuardViolation):
        run_sql("DROP TABLE marts.fct_spend", db_path=tmp_path / "missing.duckdb")
