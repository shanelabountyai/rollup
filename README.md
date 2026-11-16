# Rollup

Marketing warehouse (dbt + DuckDB) with a safe text-to-SQL layer: ask a question, see the SQL, get an answer that cites only numbers in the result.

Build-log #27. Status: **Phase 2** (guards + guarded SQL runner with hand-written SQL; no LLM yet). Phase 1 (generator + dbt models + tests) is on `main`. Spec in `docs/PRD.md`, decisions in `docs/DECISIONS.md`.

## Quick start

```bash
pip install -e '.[dev]'
make build        # seeded synthetic data -> Parquet -> dbt build (models + 213 data tests + 3 unit tests)
make docs         # dbt docs generate
make queries      # run the 12 hand-written questions through the guarded runner
make query Q="SELECT channel_key, sum(spend_usd) AS spend FROM marts.fct_spend GROUP BY 1"
make ci           # ruff, mypy, pytest, build, warehouse tests, docs, defect mutation tests
```

## Guarded SQL (Phase 2)

Every query goes through `rollup.guards.check_sql` before it reaches DuckDB, and the runner has no way around it:
sqlglot parse; one SELECT only (RU-01); only the seven `marts` tables (RU-02); no `*` once a fact table is read;
LIMIT capped at 1000 rows; read-only connection with file access, extensions and settings locked; 5-second
timeout. Refusals carry a stable code (`not_select`, `table_not_allowed`, `star_on_fact_table`, …). The
executed SQL is regenerated from the checked syntax tree, so what runs is what was checked.

DuckDB file: `data/rollup.duckdb`. Schemas: `staging`, `intermediate`, `marts`.

## Layout

- `rollup/generate.py` — seeded generator (18 months, 3 ad platforms, web, CRM). Same seed → same bytes (RU-04).
- `rollup/defects.py` — the four injected defects (UTM casing drift, duplicate leads, timezone mismatch, renamed campaign) and the dbt test that catches each.
- `rollup/guards.py` — SQL guards; `rollup/runner.py` — read-only runner with row cap and timeout;
  `rollup/query.py` — CLI; `rollup/queries/*.sql` — hand-written questions against the marts.
- `warehouse/` — dbt-duckdb project: `staging` → `intermediate` (identity stitching, campaign map) → `marts`
  (`fct_spend`, `fct_pipeline`, `fct_touches`, `dim_campaign`, `dim_channel`, `mart_funnel_weekly`, `mart_cac_by_channel`).
