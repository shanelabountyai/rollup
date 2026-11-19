# Phase 4 plan — query UI + charts + README case study

Branch `phase-4`, one PR to `main` (never merged by the agent). Source: PRD "Phases" line —
"4 UI + charts + README case study", plus the PRD's Base line (FastAPI + HTMX, D-03), its Text-to-SQL sentence
("show SQL → run → table + chart + one-paragraph answer that cites the numbers in the result") and the Guards
validator sentence (RU-03). Nothing beyond the Phase 4 line is in scope.

**LLM rule (owner decision 2026-11-15, D-29):** no live LLM calls and no API key in this run. The UI runs end to end
on the `RecordedModel` offline. The live adapter is used only when the owner opts in at his own runtime with his own
key (D-41). Tests strip any key from the environment (existing conftest fixture).

**Safety rule:** the UI calls `rollup.ask.ask()` and nothing else that touches DuckDB. Every query still goes through
`rollup.guards.check_sql` inside `execute_guarded`; the UI adds no path around them. `rollup/guards.py`,
`rollup/runner.py`, `rollup/validator.py`, `rollup/ask.py`, the golden set, its reference SQL and the eval scoring
are not changed (checked with `git diff main` in the PR).

## Scope (PRD text → Phase 4 work)

| PRD text | Phase 4 work | Where |
|---|---|---|
| "a FastAPI + HTMX UI" (Base, D-03) | FastAPI app with Jinja2 templates; HTMX (vendored, so it works offline) posts the question and swaps in the result panel. Works without JavaScript too (plain form POST renders the full page). `make ui` serves it on port 8000 (PRD). | `rollup/ui/` |
| "show SQL → run" | Panel shows the drafted SQL, then the guard outcome: passed (with the executed SQL, regenerated from the checked tree, row count, truncation, elapsed ms) or refused (status, guard code and reason). | `rollup/ui/templates/` |
| "table" | Result table (all rows up to the 1000-row guard cap; cells formatted for display only). | same |
| "chart" | A chart chosen from the result shape by fixed rules (D-42), rendered server-side as inline SVG. Its labels are result cells only, no computed axis ticks. Table-only when no rule fits, with the reason shown. | `rollup/ui/chart.py` |
| "one-paragraph answer that cites the numbers in the result" (RU-03) | The panel shows only `AskResult.answer`, which `ask()` has already validated (model paragraph or fallback). A rejected model paragraph is **never** rendered, nor are the violation messages (they quote the invented numbers); the panel says the paragraph was rejected and how many numbers failed. Refusals show their reason and no answer digits. | `rollup/ui/app.py` |
| "README case study" | README rewritten around a case study for a hiring-manager reader: problem, architecture, guards, eval method and committed eval numbers (cited by file), what is not verified, how to run. Numbers come only from a run file produced in this session and committed (`docs/eval/`). | `README.md`, `docs/eval/` |

Not in Phase 4: hosting/deploys, auth, multi-user state, new marts, any change to guards/validator/eval, live-model
runs.

## Tasks

1. [x] Plan (this file) committed first.
2. [x] Dependencies: `fastapi`, `jinja2`, `uvicorn`, `python-multipart` (runtime) and `httpx` (TestClient, dev) (D-40).
3. [x] `rollup/ui/chart.py`: chart rules (D-42) → `ChartSpec` → inline SVG.
4. [x] `rollup/ui/app.py` + templates + vendored `htmx.min.js`: `create_app(model=..., db_path=..., manifest=...)`,
   `GET /` (form + recorded example questions), `POST /ask` (HTMX partial or full page), `GET /healthz`.
   Model choice: recorded by default, live only on explicit opt-in with a key present (D-41).
5. [x] `make ui` target; `python -m rollup.ui`.
6. [x] Tests (below); they run inside `make ci` (unit tests in `make test`, route tests in `make test-warehouse`).
7. [x] Eval run on the recorded drafts committed under `docs/eval/` for the case study (D-44).
8. [ ] README case study + status line, NEXT.md, DECISIONS rows, PR.

## Acceptance items and the tests that prove them

| Item | Proof |
|---|---|
| Ask → SQL → guard result → table → validated answer → chart, offline on the recorded model | `tests/test_ui.py` (warehouse, FastAPI `TestClient`): answered question renders drafted SQL, executed SQL, "passed" guard badge, table rows equal to `ask()`'s rows, the shown answer, and an `<svg>` chart. Both the HTMX partial and the no-JS full page. |
| Refused query shows code and reason, no numbers, no table | `test_ui.py`: the recorded DELETE draft → `refused_guard`, code `not_select`, reason shown; no `<table>`, no chart, answer text has no digits. Also a model refusal (`refused_question`) and an unknown question on the recorded model (`model_error`). |
| RU-03 holds on what the UI shows | `test_ui.py`: for a recorded dishonest paragraph (golden 01, invented total), the rejected paragraph text and its violation strings do not appear in the HTML; the shown answer re-validates against the rows. Over every recorded question: the answer paragraph block in the HTML equals `ask().answer` (escaped), and that answer validates. |
| No path around the guards | `test_ui.py`: a spy on `rollup.runner.check_sql` sees every draft the UI runs; the DB file sha256 is unchanged after the whole recorded set goes through the UI; the app module never imports `duckdb` execution helpers other than `open_readonly`. `git diff main -- rollup/guards.py rollup/runner.py rollup/validator.py rollup/ask.py rollup/eval/` is empty (PR). |
| Chart type chosen from the result shape | `tests/test_chart.py` (unit): date + number → line; text + number (2–30 rows) → bar; one row, no numeric column, too many categories, negative/NULL handling, truncated result → none with a reason; SVG labels are only cell strings (no number appears in the SVG that is not a formatted cell). Route test checks the line chart for the monthly-spend question and the bar chart for spend-by-platform. |
| Live model only by opt-in with a key | `test_ui.py` (unit): `select_model()` returns the recorded model by default and when the key is missing; raises a clear error for `live` without a key; never constructs a live client in tests. |
| Phases 1–3 still hold | All earlier tests run unchanged in `make ci`; `make eval` still reports the pinned recorded numbers. |

## Gate

`make ci` green locally and GitHub CI green on the PR head: ruff (lint + format), mypy strict, pytest (unit incl.
chart rules), `make build` (RU-04/RU-05), `make test-warehouse` (Phase 2–3 tests + UI route tests), `make eval`,
`dbt docs generate`, defect mutation tests. No test deleted, skipped or weakened; no guard or validator rule changed.

## Status

- [x] Gate run + PR (#6; local `make ci` and GitHub CI green; merged 2026-11-18 after Shane's approval)
