"""Guarded SQL runner (PRD guards G6 read-only connection and G7 timeout; Phase 2).

``run_sql`` always calls ``rollup.guards.check_sql`` first; there is no argument that skips it. The statement
that reaches DuckDB is the one regenerated from the checked tree. The connection is opened read-only with
external access (files, network, extensions) off and the configuration locked, so even a guard bug cannot
write, read files or loosen settings (D-23).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from rollup.guards import DEFAULT_MAX_ROWS, GuardedQuery, check_sql

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "rollup.duckdb"

READONLY_CONFIG: dict[str, str | bool | int | float | list[str]] = {
    "enable_external_access": False,
    "autoinstall_known_extensions": False,
    "autoload_known_extensions": False,
    "lock_configuration": True,  # must stay last: nothing can be SET after this
}


class QueryTimeout(Exception):
    """The query ran longer than the timeout and was interrupted."""


class QueryError(Exception):
    """DuckDB rejected a query that passed the guards (e.g. unknown column)."""


@dataclass(frozen=True)
class QueryResult:
    guarded: GuardedQuery
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool  # more rows existed than the row cap
    elapsed_ms: float

    @property
    def sql(self) -> str:
        """The SQL that was executed."""
        return self.guarded.sql


def default_db_path() -> Path:
    return Path(os.environ.get("ROLLUP_DUCKDB_PATH", DEFAULT_DB_PATH))


def open_readonly(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open the warehouse read-only with external access off and configuration locked (G6)."""
    path = Path(db_path) if db_path is not None else default_db_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `make build` first")
    con = duckdb.connect(str(path), read_only=True, config=READONLY_CONFIG)
    mode = con.execute("SELECT current_setting('access_mode')").fetchone()
    if mode is None or mode[0] != "read_only":
        con.close()
        raise RuntimeError(f"warehouse connection is not read-only (access_mode={mode})")
    return con


def execute_guarded(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> QueryResult:
    """Guard, then run on an already-open read-only connection with a timeout (G7)."""
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")
    guarded = check_sql(sql, max_rows=max_rows)
    timer = threading.Timer(timeout_s, con.interrupt)
    started = time.perf_counter()
    timer.start()
    try:
        cursor = con.execute(guarded.sql)
        columns = [d[0] for d in cursor.description or []]
        rows = cursor.fetchall()
    except duckdb.InterruptException as e:
        raise QueryTimeout(f"query exceeded {timeout_s:g}s and was interrupted") from e
    except duckdb.Error as e:
        raise QueryError(str(e).splitlines()[0][:500]) from e
    finally:
        timer.cancel()
    elapsed_ms = (time.perf_counter() - started) * 1000
    truncated = len(rows) > guarded.row_cap
    return QueryResult(
        guarded=guarded,
        columns=columns,
        rows=rows[: guarded.row_cap],
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


def run_sql(
    sql: str,
    *,
    db_path: Path | str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> QueryResult:
    """Guard and run one SELECT against the marts on a fresh read-only connection."""
    check_sql(sql, max_rows=max_rows)  # refuse before touching the database at all
    con = open_readonly(db_path)
    try:
        return execute_guarded(con, sql, max_rows=max_rows, timeout_s=timeout_s)
    finally:
        con.close()
