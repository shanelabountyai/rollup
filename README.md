# Rollup

Marketing warehouse (dbt + DuckDB) with a safe text-to-SQL layer: ask a question, see the SQL, get an answer that cites only numbers in the result.

Build-log #27. Status: **Phase 1** (generator + dbt models + tests). Spec in `docs/PRD.md`, decisions in `docs/DECISIONS.md`.

## Quick start

```bash
pip install -e '.[dev]'
make build        # seeded synthetic data -> Parquet -> dbt build (models + 191 tests)
make docs         # dbt docs generate
make ci           # ruff, mypy, pytest, build, docs, defect mutation tests
```

DuckDB file: `data/rollup.duckdb`. Schemas: `staging`, `intermediate`, `marts`.

## Layout

- `rollup/generate.py` — seeded generator (18 months, 3 ad platforms, web, CRM). Same seed → same bytes (RU-04).
- `rollup/defects.py` — the four injected defects (UTM casing drift, duplicate leads, timezone mismatch, renamed campaign) and the dbt test that catches each.
- `warehouse/` — dbt-duckdb project: `staging` → `intermediate` (identity stitching, campaign map) → `marts`
  (`fct_spend`, `fct_pipeline`, `fct_touches`, `dim_campaign`, `dim_channel`, `mart_funnel_weekly`, `mart_cac_by_channel`).
