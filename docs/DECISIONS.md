# #27 Rollup — marketing warehouse + safe text-to-SQL — decisions

Made by Claude on 2026-11-13 while Shane was away. Each is a default he can change.

| ID | Problem | Options | Decision | Change it |
|---|---|---|---|---|
| D-01 | Warehouse engine | DuckDB, Postgres, BigQuery sandbox | **DuckDB** — zero infra, dbt-duckdb adapter | swap dbt profile |
| D-02 | SQL safety | prompt-only, parser + allowlist + read-only conn | **parser + allowlist + read-only** | none recommended |
| D-03 | UI stack | Next.js, FastAPI + HTMX | **FastAPI + HTMX** — one language with dbt | Next.js if you want it on the shared stack |
| D-04 | Eval scoring | SQL text match, result-set equivalence | **result-set equivalence** | — |
| D-05 | Name / number | Rollup, #27 | as stated | rename before repo creation |
