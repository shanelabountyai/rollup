# Rollup

Marketing warehouse (dbt + DuckDB) with a safe text-to-SQL layer: ask a question, see the SQL, get an answer that cites only numbers in the result.

Build-log #27. Status: **Phase 3** (SQL drafting behind a model interface, RU-03 answer validator, 40-question golden-set eval). Phases 1–2 (generator, dbt models, guards, guarded runner) are on `main`. Phase 3 was built and tested against **recorded** model responses only; no live LLM has been called yet (D-29). Spec in `docs/PRD.md`, decisions in `docs/DECISIONS.md`.

## Quick start

```bash
pip install -e '.[dev]'
make build        # seeded synthetic data -> Parquet -> dbt build (models + 213 data tests + 3 unit tests)
make docs         # dbt docs generate
make queries      # run the 12 hand-written questions through the guarded runner
make query Q="SELECT channel_key, sum(spend_usd) AS spend FROM marts.fct_spend GROUP BY 1"
make ask Q="Which five campaigns have the highest lifetime spend?"   # recorded model, offline
make eval         # golden-set eval on recorded drafts -> data/eval/run.json
make ci           # ruff, mypy, pytest, build, warehouse tests, eval, docs, defect mutation tests
```

## Guarded SQL (Phase 2)

Every query goes through `rollup.guards.check_sql` before it reaches DuckDB, and the runner has no way around it:
sqlglot parse; one SELECT only (RU-01); only the seven `marts` tables (RU-02); no `*` once a fact table is read;
LIMIT capped at 1000 rows; read-only connection with file access, extensions and settings locked; 5-second
timeout. Refusals carry a stable code (`not_select`, `table_not_allowed`, `star_on_fact_table`, …). The
executed SQL is regenerated from the checked syntax tree, so what runs is what was checked.

## Asking questions (Phase 3)

`python -m rollup.ask "<question>"`: the model drafts one SELECT against the marts. Its context is the schema and
column descriptions of the seven marts, taken from the dbt manifest. The draft then goes through the Phase 2 guards
and the read-only runner unchanged. The model writes a one-paragraph answer, and the RU-03 validator checks that
every number in it is in the result set. If the paragraph fails, it is replaced by a paragraph that quotes result
cells only. A question the marts can't answer ends in a refusal with no numbers. So does a draft that fails a guard,
errors or times out.

The model sits behind `rollup.llm.DraftModel`. The default `RecordedModel` replays `rollup/eval/recorded.json` and
needs no network. Those responses were written in-session, including deliberately bad ones (D-37). An optional live
adapter exists (`pip install -e '.[live]'`, `ANTHROPIC_API_KEY`, `ROLLUP_LLM_MODEL`, `--model live`). It has not
been run yet.

**Eval:** `make eval` scores 40 golden questions by result-set equivalence against hand-written reference SQL
(`rollup/eval/golden/`), plus 8 unanswerable questions. It writes `data/eval/run.json` for Yardstick (#26). On the
recorded drafts it scores 27/40 golden and 7/8 refusals. **These numbers measure the pipeline on recorded drafts,
not a live model.** `--model reference` must score 40/40.

DuckDB file: `data/rollup.duckdb`. Schemas: `staging`, `intermediate`, `marts`.

## Layout

- `rollup/generate.py` — seeded generator (18 months, 3 ad platforms, web, CRM). Same seed → same bytes (RU-04).
- `rollup/defects.py` — the four injected defects (UTM casing drift, duplicate leads, timezone mismatch, renamed campaign) and the dbt test that catches each.
- `rollup/guards.py` — SQL guards; `rollup/runner.py` — read-only runner with row cap and timeout;
  `rollup/query.py` — CLI; `rollup/queries/*.sql` — hand-written questions against the marts.
- `rollup/schema_context.py` — marts-only drafting context from the dbt manifest; `rollup/llm.py` — model interface,
  recorded/reference/live models; `rollup/validator.py` — RU-03; `rollup/ask.py` — the pipeline and CLI.
- `rollup/eval/` — golden questions, refusal set, recorded responses, equivalence scorer, runner;
  `scripts/author_recording.py` — how the recorded responses were made.
- `warehouse/` — dbt-duckdb project: `staging` → `intermediate` (identity stitching, campaign map) → `marts`
  (`fct_spend`, `fct_pipeline`, `fct_touches`, `dim_campaign`, `dim_channel`, `mart_funnel_weekly`, `mart_cac_by_channel`).
