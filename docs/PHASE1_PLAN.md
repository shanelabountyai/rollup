# Phase 1 plan — generator + dbt models + tests (no LLM)

Branch `kickoff`, PR #1 (never merged by the agent). Phase 2+ is out of scope.

## Deliverables

1. **Synthetic data generator** — `rollup/generate.py` (`python -m rollup.generate --seed 27 --out data/raw`).
   - numpy `Generator(PCG64(seed))`, fixed start date 2025-05-01, 18 months (548 days). No wall-clock input.
   - Writes Parquet (pyarrow) with deterministic row order: `ad_spend`, `campaigns`, `web_sessions`,
     `form_fills`, `crm_contacts`, `crm_leads`, `crm_opportunities`, `crm_opportunity_stage_history`.
   - 3 ad platforms (google_ads, linkedin_ads, meta_ads), ~18 campaigns.
   - Injected defects (each documented in `rollup/defects.py` and caught by a custom dbt test):
     - **D1 UTM casing drift** — `utm_source/medium/campaign` randomly upper/title/padded.
     - **D2 duplicate leads** — ~6% of leads re-created with email case/whitespace variants.
     - **D3 timezone mismatch** — web sessions are UTC timestamps; form fills are naive
       `America/New_York` wall-clock timestamps.
     - **D4 renamed campaign** — one campaign's name changes mid-period (same id on the platform, new
       name in UTMs after the rename date).
2. **dbt-duckdb project** in `warehouse/` reading Parquet via `read_parquet` sources.
   - `staging/` — one `stg_*` per source: typed, trimmed, lower-cased, timezone-normalised to UTC.
   - `intermediate/` — `int_leads_stitched` (identity stitching on normalised email), `int_campaign_map`
     (all historical names/UTM keys → canonical campaign id), `int_sessions_attributed`.
   - `marts/` — `fct_spend`, `fct_pipeline`, `fct_touches`, `dim_campaign`, `dim_channel`,
     `mart_funnel_weekly`, `mart_cac_by_channel`.
   - Generic tests on every model (unique, not_null, relationships, accepted_values) + custom singular tests per defect.
   - Column descriptions on every mart column (feeds Phase 3 schema context).
3. **`make build`** = generate + `dbt build`. Also `make test`, `make lint`, `make docs`, `make repro`.
4. **Tests (pytest)** — RU-04: two generations with the same seed produce byte-identical Parquet content hashes;
   different seed differs; each defect is actually present in raw data.
5. **CI** (`.github/workflows/ci.yml`) — ruff, mypy, pytest, `make build`, `dbt docs generate`.

## Gate
- `dbt build` green (RU-05), RU-04 pytest green, `dbt docs generate` succeeds. Results reported in PR body.

## Status
- [x] Plan + PR opened
- [x] Generator (`rollup/generate.py`, `rollup/defects.py`)
- [x] dbt project (19 models, 191 tests incl. 12 custom singular)
- [x] PR #1 review fixes: local business-day reporting calendar (D-15), pinned deps (D-14), 3 reconciliation tests
- [x] Tests + CI (pytest 11 + 4 mutation; `.github/workflows/ci.yml`)
- [x] Gate run + PR body — passed locally 2026-11-14 (see PR #1)

Note: raw tables also include `campaigns` (catalogue snapshot) beyond the plan list; the
D3 timezone defect landed on form fills (local) vs sessions (UTC) rather than ad spend — see D-09.
