"""CLI for the guarded runner.

    python -m rollup.query "SELECT channel_key, sum(spend_usd) FROM marts.fct_spend GROUP BY 1"
    python -m rollup.query --name cac_by_channel_quarter
    python -m rollup.query --all            # run every hand-written query
    python -m rollup.query --list

Exit codes: 0 ok, 2 refused by a guard, 3 timeout, 4 DuckDB error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from rollup.guards import DEFAULT_MAX_ROWS, GuardViolation
from rollup.queries import load_queries
from rollup.runner import DEFAULT_TIMEOUT_S, QueryError, QueryResult, QueryTimeout, run_sql

EXIT_OK, EXIT_REFUSED, EXIT_TIMEOUT, EXIT_ERROR = 0, 2, 3, 4


def _fmt(value: Any) -> str:
    return "NULL" if value is None else str(value)


def format_table(result: QueryResult, max_print: int = 50) -> str:
    rows = [[_fmt(v) for v in row] for row in result.rows[:max_print]]
    widths = [max([len(c), *(len(r[i]) for r in rows)]) for i, c in enumerate(result.columns)]
    line = " | ".join(c.ljust(w) for c, w in zip(result.columns, widths, strict=True))
    out = [line, "-+-".join("-" * w for w in widths)]
    out += [" | ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)) for r in rows]
    more = len(result.rows) - len(rows)
    tail = f"{len(result.rows)} row(s)" + (f", {more} not shown" if more else "")
    tail += ", truncated at row cap" if result.truncated else ""
    out.append(f"({tail}; {result.elapsed_ms:.0f} ms)")
    return "\n".join(out)


def _run_one(label: str, sql: str, args: argparse.Namespace) -> int:
    print(f"== {label}")
    try:
        result = run_sql(sql, db_path=args.db, max_rows=args.max_rows, timeout_s=args.timeout)
    except GuardViolation as e:
        print(f"REFUSED [{e.code}] {e.message}")
        return EXIT_REFUSED
    except QueryTimeout as e:
        print(f"TIMEOUT {e}")
        return EXIT_TIMEOUT
    except QueryError as e:
        print(f"ERROR {e}")
        return EXIT_ERROR
    print(f"-- executed:\n{result.sql}\n")
    print(format_table(result))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rollup.query", description="Run guarded SQL against the Rollup marts.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("sql", nargs="?", help="a single SELECT against marts.*")
    src.add_argument("--name", help="run a hand-written query from rollup/queries")
    src.add_argument("--all", action="store_true", help="run every hand-written query")
    src.add_argument("--list", action="store_true", help="list hand-written queries")
    p.add_argument("--db", default=None, help="DuckDB path (default: $ROLLUP_DUCKDB_PATH or data/rollup.duckdb)")
    p.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = p.parse_args(argv)

    queries = load_queries()
    if args.list:
        for q in queries.values():
            print(f"{q.name:32} {q.question}")
        return EXIT_OK
    if args.name:
        if args.name not in queries:
            print(f"unknown query {args.name!r}; try --list", file=sys.stderr)
            return EXIT_ERROR
        q = queries[args.name]
        return _run_one(f"{q.name}: {q.question}", q.sql, args)
    if args.all:
        codes = [_run_one(f"{q.name}: {q.question}", q.sql, args) for q in queries.values()]
        return max(codes, default=EXIT_OK)
    return _run_one("query", args.sql, args)


if __name__ == "__main__":
    sys.exit(main())
