# #27 Rollup — marketing warehouse + safe text-to-SQL — decisions

Made by Claude on 2026-11-13 while Shane was away. Each is a default he can change.

| ID | Problem | Options | Decision | Change it |
|---|---|---|---|---|
| D-01 | Warehouse engine | DuckDB, Postgres, BigQuery sandbox | **DuckDB** — zero infra, dbt-duckdb adapter | swap dbt profile |
| D-02 | SQL safety | prompt-only, parser + allowlist + read-only conn | **parser + allowlist + read-only** | none recommended |
| D-03 | UI stack | Next.js, FastAPI + HTMX | **FastAPI + HTMX** — one language with dbt | Next.js if you want it on the shared stack |
| D-04 | Eval scoring | SQL text match, result-set equivalence | **result-set equivalence** | — |
| D-05 | Name / number | Rollup, #27 | as stated | rename before repo creation |
| D-06 | Proving custom tests catch each defect | trust the tests, mutation-test them | **mutation test**: a dbt var `unfix: D1..D4` switches one fix off; `make test-mutation` asserts the matching custom test fails. Added by Claude 2026-11-14 (Phase 1, unattended) | delete `tests/test_defect_detection.py` and the `unfix` branches in `warehouse/macros/utils.sql` |
| D-07 | Attribution credit in marts | one model everywhere, per-mart choice | **funnel = last touch (converting session); CAC = first touch**; `fct_touches` also carries linear weights. Added 2026-11-14 | change the `coalesce(..._touch_channel_key)` in `mart_funnel_weekly` / `mart_cac_by_channel` |
| D-08 | Touch window + identity | all sessions, sessions up to first lead | **sessions by the form-fill visitor (anonymous_id) up to first lead creation**; person = md5(lower(trim(email))). Added 2026-11-14 | edit `int_person_touches` / `person_key` macro |
| D-09 | Timezones | everything UTC, local reporting tz | **warehouse is UTC**; company/form-tool tz is America/New_York; synthetic sessions fall 07:00–23:00 local so no DST-ambiguous fills. Added 2026-11-14 | `local_tz` var in `dbt_project.yml`, `LOCAL_TZ` in generator |
| D-10 | Type checking with pandas | mypy strict + pandas-stubs, strict without stubs | **mypy strict, no pandas-stubs** (stubs produced ~30 false positives on pandas scalars) | add `pandas-stubs` to dev deps and fix annotations |
| D-11 | Generated data in git | commit Parquet, regenerate | **regenerate** — `data/` is gitignored; `make build` recreates byte-identical files (RU-04) | remove `data/` from `.gitignore` |
| D-12 | Schema layout / materialisation | dbt default `main_<schema>`, layer names | **schemas `staging` (views), `intermediate` and `marts` (tables)** via a `generate_schema_name` override; Phase 2 allowlist = `marts` | edit `dbt_project.yml` / `macros/generate_schema_name.sql` |
| D-13 | PR #1 state | ready for review, draft | **draft** until Shane reviews; never merged by the agent | mark ready in GitHub |
| D-14 | Dependency pinning for RU-04 | minimums, exact pins | **exact pins for numpy 2.5.4 / pandas 3.1.1 / pyarrow 26.0.1** (from PR #1 review): byte-identical output depends on the RNG stream and Parquet writer | bump pins deliberately and re-baseline hashes |
| D-15 | Reporting calendar (PR #1 review must-fix) | UTC dates, local business dates | **timestamps stay UTC; every reporting date/week/month column is the America/New_York business day** — the calendar spend is reported in. Guarded by `assert_paid_sessions_on_spend_day` (fails on 36,783 sessions if UTC dating returns). Supersedes the date part of D-09 | `local_date` macro in `warehouse/macros/utils.sql` |
| D-16 | DST fall-back hour (review note on D-09) | generate sessions at all hours, keep 07:00–23:00 local | **keep 07:00–23:00**: naive local form-fill times in the repeated 01:00 hour are inherently ambiguous, so the D3 test could not be exact there. Known gap: the fall-back hour is untested | widen hours in `_local_times_to_utc` and relax `assert_form_fill_after_session` |
| D-17 | CAC definition (review note on D-07) | month spend / month wins, cohort CAC | **documented as-is**: `cac_usd` = that month's paid spend ÷ deals closed-won that month whose first touch was the channel (not a spend cohort). D-07 attribution split remains **Shane's call** | change `mart_cac_by_channel` |
