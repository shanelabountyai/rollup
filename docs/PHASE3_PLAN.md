# Phase 3 plan — LLM drafting + answer validator + golden-set eval

Branch `phase-3`, one PR to `main` (never merged by the agent). Source: PRD "Phases" line —
"3 LLM drafting + answer validator + golden-set eval", plus the PRD's Text-to-SQL, Guards (validator sentence),
refusal-path and Eval paragraphs. Phase 4 (UI, table/chart rendering, README case study) is out of scope.

**LLM rule (owner decision 2026-11-15, D-29):** no live LLM API calls and no API keys in this run. The drafting
model sits behind an interface. Everything is built and tested against a recorded model (committed fixture
responses, including deliberately bad SQL and dishonest answer paragraphs) plus the PRD's fallback path. The
golden-set eval runs on the recorded drafts, so its numbers measure **the pipeline on recorded drafts, not a live
model**. Running it live is an owner hand step.

## Scope (PRD text → Phase 3 work)

| PRD text | Phase 3 work | Where |
|---|---|---|
| "LLM drafts SQL against the **marts only** (schema + column descriptions from dbt manifest as context)" | Schema context built from `warehouse/target/manifest.json`: only models in schema `marts`, with model and column descriptions and column types from the built DB. Prompt builder. Model interface (`DraftModel` protocol) with a recorded implementation and an optional live adapter that is never called in tests or CI. | `rollup/schema_context.py`, `rollup/llm.py` |
| "→ guards → show SQL → run" | `ask()` pipeline: the draft goes through the Phase 2 `execute_guarded` path **unchanged** (no guard is loosened, no bypass). The executed SQL is kept on the result so it can be shown. | `rollup/ask.py` |
| "one-paragraph answer that cites the numbers in the result" / "the answer paragraph may only use numbers present in the result set (validator)" (RU-03) | `validate_answer(paragraph, result)`: every number token in the paragraph must match a value in the result set (rules in D-32). A paragraph that fails is never shown: the pipeline falls back to a deterministic paragraph built only from result cells, which is itself validated. | `rollup/validator.py`, `rollup/ask.py` |
| "Refusal path for questions the marts can't answer" | The model may return a refusal instead of SQL; the pipeline also refuses when the draft fails a guard, errors or times out. Every refusal carries a reason and a code; no number is ever shown for a refused question. | `rollup/ask.py` |
| "Eval: 40 golden questions with hand-written reference SQL; score = result-set equivalence (not SQL text match). Yardstick (#26) consumes the run file." | 40 golden questions with reference SQL; result-set equivalence scorer (D-33); a separate refusal set of unanswerable questions; `make eval` writes a JSON run file (D-35). | `rollup/eval/` |

Not in Phase 3: chart rendering, the web UI, table formatting beyond the CLI, README case study (Phase 4).

## Tasks

1. [x] Plan (this file) committed first.
2. [x] `rollup/schema_context.py`: manifest → marts-only context + prompt text.
3. [x] `rollup/llm.py`: `DraftModel` protocol, `Draft` (SQL or refusal), `RecordedModel` (fixtures), `ReferenceModel`
   (drafts the golden reference SQL, used to prove the harness), optional `AnthropicModel` live adapter (lazy import,
   needs a key and a model id from the environment; never constructed in tests with a real client).
4. [x] `rollup/validator.py`: RU-03 number extraction and matching; deterministic fallback paragraph.
5. [x] `rollup/ask.py` + `python -m rollup.ask` CLI: question → draft → guards → run → answer → validate/fallback.
6. [x] `rollup/eval/`: 40 golden `.sql` files, refusal set, recorded fixtures (good drafts, wrong-but-safe drafts,
   guard-violating drafts, erroring drafts, dishonest paragraphs), equivalence scorer, runner, `make eval`.
7. [x] Tests (below), CI step, DECISIONS rows, README status, PR.

## Acceptance items and the tests that prove them

| Item | Proof |
|---|---|
| Drafting sees the marts only | `test_schema_context.py` (warehouse): context lists exactly the 7 allowlisted marts (= `MART_TABLES`) with every column and its description; no staging/intermediate/source name appears in the prompt. Unit: context builder ignores non-mart nodes in a synthetic manifest. |
| Every draft goes through the Phase 2 guards and runner unchanged | `test_ask.py`: a spy on `check_sql` sees every draft; recorded guard-violating drafts (DELETE, DROP, multi-statement, staging/intermediate/information_schema reads, `read_csv`, `SELECT *` on a fact table, ATTACH, COPY) are refused with the same codes `check_sql` gives; the DB file sha256 is unchanged after the whole eval; `git diff main -- rollup/guards.py rollup/runner.py` is empty (checked in the PR). |
| RU-03 every number in an answer paragraph appears in its result set | `test_validator.py`: unit cases (thousands separators, decimals, `$`, `%` both as ratio×100 and as a percent column, k/M/B suffixes, negatives, dates, years, quarters, names containing digits); hypothesis: a paragraph built from result cells always validates, and inserting any number not derivable from the result always fails; the fallback paragraph always validates. `test_ask.py`: every recorded dishonest paragraph is rejected and replaced; on every `ask()` outcome, the shown answer re-validates against the result. |
| Refusal path | `test_ask.py` + eval: every refusal-set question ends in a refusal with no numbers; model refusals, guard refusals, DuckDB errors and timeouts each map to their status. |
| Golden-set eval: 40 questions, result-set equivalence | `test_eval.py`: exactly 40 golden questions, each reference SQL passes the guards unchanged and returns rows within 5 s; `ReferenceModel` scores 40/40 (harness sanity); scorer unit + property tests (row order, column order and alias changes keep equivalence when unordered; any changed value, missing/extra row or dropped column breaks it); the recorded-draft run scores the pinned numbers below. |
| Phase 1–2 still hold | All earlier tests run unchanged in `make ci`. |

## Gate

`make ci` green locally and GitHub CI green on the PR head (D-30): ruff (lint + format), mypy strict, pytest
(unit + hypothesis), `make build` (RU-04/RU-05), `make test-warehouse` (Phase 2 tests + schema context, ask
pipeline and eval tests), `make eval` on the recorded drafts (writes the run file and fails if any invariant breaks:
a guard-violating draft executed, a refused question showed a number, or a shown answer failed RU-03),
`dbt docs generate`, defect mutation tests. No test deleted, skipped or weakened; no guard loosened.

## Status

- [ ] Gate run + PR
