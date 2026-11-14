# Phase 2 plan — guards + SQL runner with hand-written SQL (no LLM)

Branch `phase-2`, one PR to `main` (never merged by the agent). Source: PRD "Phases" line —
"2 guards + SQL runner with hand-written SQL". Phase 3 (LLM drafting, the answer-paragraph validator RU-03,
the question-level refusal path and the 40-question golden-set eval) and Phase 4 (UI, charts, case study) are
out of scope. No LLM API calls.

## Scope (from the PRD's Text-to-SQL "Guards" paragraph, minus the Phase 3 answer validator)

All in code, not prompt:

| # | PRD guard | Where |
|---|---|---|
| G1 | parse with sqlglot | `rollup/guards.py` `check_sql` |
| G2 | single `SELECT` only (one statement; root is a SELECT or a set operation of SELECTs; no DML/DDL/command node anywhere in the tree) | `guards.py` |
| G3 | allowlisted schemas/tables — only the 7 `marts` tables (D-12); CTE references resolved per scope with sqlglot's scope analysis; table functions and file paths rejected | `guards.py` |
| G4 | no `*` on fact tables (`fct_*`); `COUNT(*)` is not a projection and stays allowed | `guards.py` |
| G5 | row limit injected on the outer query | `guards.py` (rewrites the AST; the executed SQL is regenerated from the checked AST) |
| G6 | read-only DuckDB connection (plus external access off and configuration locked, defence in depth) | `rollup/runner.py` |
| G7 | 5-second timeout | `runner.py` (`connection.interrupt()` from a timer) |

Plus: a **SQL runner** (`rollup/runner.py`, CLI `python -m rollup.query`) that always routes through the guards
(no bypass argument), and a **library of hand-written SQL** (`rollup/queries/*.sql`) answering typical
marketing-ops questions against the marts, run through the runner.

## Tasks

1. [x] Plan (this file) committed first.
2. [ ] `rollup/guards.py`: `check_sql(sql, max_rows) -> GuardedQuery` or `GuardViolation(code, message)`.
3. [ ] `rollup/runner.py`: `run_sql(sql, db_path, max_rows, timeout_s) -> QueryResult`; `open_readonly(db_path)`.
4. [ ] `rollup/queries/`: 12 hand-written `.sql` files + loader; `rollup/query.py` CLI; `make query`, `make queries`.
5. [ ] Tests: guard unit tests (attack corpus), hypothesis property tests for RU-01/RU-02, runner tests against
   the built warehouse, hand-written query tests with reconciliation checks.
6. [ ] CI: install dev deps incl. hypothesis; run the warehouse-backed tests after `make build`.
7. [ ] DECISIONS rows, README status, PR with gate results.

## Invariants and the tests that prove them

| Item | Proof |
|---|---|
| **RU-01** no non-SELECT statement ever executes | `test_guards.py`: corpus of DML/DDL/PRAGMA/ATTACH/COPY/SET/INSTALL/CALL/EXPORT/multi-statement/CTE-wrapped writes all refused. `test_guards_property.py`: hypothesis generates non-SELECT statements and `SELECT …; <non-select>` stacks → always refused. `test_runner.py`: a recording connection proves every statement the runner executes re-parses as a single SELECT; running the full attack corpus leaves the DuckDB file's sha256 unchanged; the connection itself refuses writes and `SET` (read-only + locked config). |
| **RU-02** no table outside the allowlist is read | `test_guards_property.py`: hypothesis builds queries over random mixes of every table in the built DB (all schemas incl. `information_schema`) and random names, in FROM/JOIN/subquery/CTE/set-op positions → accepted iff every referenced real table is an allowlisted mart. `test_guards.py`: CTE-shadowing trick, catalog qualifiers, table functions (`read_csv`, `query`, `range`), quoted file paths refused. `test_runner.py`: every non-mart relation in the DB is refused by the runner; the connection cannot read Parquet (staging views fail) or local files. `test_allowlist_matches_marts`: allowlist == `warehouse/models/marts/*.sql` == tables in the `marts` schema. |
| G4 no `*` on fact tables | unit tests: `*`, `t.*`, `* EXCLUDE`, `COLUMNS(*)`, star in subquery over `fct_*` refused; `COUNT(*)` and `*` on dims/marts allowed. |
| G5 row limit | unit + runner tests: no LIMIT → cap injected; larger LIMIT → capped; smaller kept; `truncated` flag set exactly when more rows exist; non-literal LIMIT / FETCH refused. |
| G7 timeout | runner test: a cross join over `fct_touches` is interrupted at the configured timeout and raises `QueryTimeout`; the connection is usable afterwards; default is 5.0 s. |
| Hand-written SQL | `test_queries.py`: all 12 pass guards, run under the timeout, return rows, and reconcile with direct reads (total spend, first-touch vs last-touch wins/revenue totals, funnel vs CAC). |
| Phase 1 still holds | RU-04 (`test_generate.py`), RU-05 (`make build`), docs, mutation tests unchanged. |

## Gate

The PRD names no Phase 2-specific gate beyond the guards themselves and RU-01/RU-02 (see D-21). Gate =
`make ci` green locally and GitHub CI green on the PR head:
ruff (lint + format), mypy strict, pytest (unit + hypothesis property tests + warehouse-backed runner/query tests),
`make build` (RU-04/RU-05), `dbt docs generate`, defect mutation tests. No test deleted, skipped or weakened.

## Status

- [ ] Gate run + PR
