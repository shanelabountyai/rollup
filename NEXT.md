# Next — Rollup after Phase 4

Written 2026-11-18 by an unattended Claude run. PR #6 "Rollup Phase 4: query UI, charts, README case study" was
approved by Shane and **merged into `main` on 2026-11-18** (merge commit 1b9b11e).

## What Phase 4 built

- `rollup/ui/`: FastAPI + HTMX query UI (D-03). Question → drafted SQL → guard result (passed + executed SQL, or
  refused + code + reason) → result table → validated answer paragraph → chart. HTMX is vendored (works offline);
  the page also works without JavaScript. `make ui` serves it on http://127.0.0.1:8000 with the recorded model.
- `rollup/ui/chart.py`: chart picked from the result shape (line / bar / none with a reason); every SVG label is a
  result cell (D-42).
- The UI never renders a paragraph RU-03 rejected, or its violation messages (D-43). It runs no SQL of its own; it
  calls `rollup.ask.ask()`, so every draft still goes through `check_sql` and the read-only runner.
- Tests: `tests/test_chart.py` (rules + hypothesis check that SVG text passes RU-03), `tests/test_ui.py` (TestClient
  routes on the recorded model: answered, guard refusal, model refusal, unknown question, RU-03 rejection, chart
  types, all 48 recorded questions through the UI with a `check_sql` spy and a DB-unchanged hash).
- README rewritten as a case study; eval numbers cited from committed run files in `docs/eval/` (D-44).
- DECISIONS D-40..D-46.

## Review run 2026-11-18 (scheduled, after PR #6 was merged)

PR #6 was merged at 15:25 UTC, before this review ran (D-48). One independent review, findings spot-checked:

- **Must-fix M1 (fixed on `phase-4`, not yet in main):** non-answer pages rendered unchecked `reason` text: a model
  `REFUSE:` explanation with invented numbers, or a DuckDB error quoting a cell value (`'44900.00x'`). Fix:
  `shown_reason` in `rollup/ui/app.py` (D-47) + `test_non_answer_reasons_show_no_numbers`. To land it, open a PR
  `phase-4` → `main` (only the review commits differ).
- Should-fix, left open: README reference-run RU-03 cell says "n/a" but `docs/eval/reference-run.json` says 40;
  the "owner-reported live run" numbers have no committed run file; an all-NULL first numeric column lets the next
  numeric column be charted (D-42 says "first numeric column only"); no route-level XSS test.
- Gate: `make ci` exit 0 (lint, mypy, 324 + 137 warehouse + 4 mutation tests, dbt PASS=235, eval 27/40 golden,
  7/8 refusal, unchanged).

## Follow-up on owner "go" (2026-11-18)

- D-49: D-31 amended: refusals show no numbers *from the data*; guard reasons (fixed strings about the drafted SQL)
  stay visible. Page and README wording updated.
- D-50: the UI only answers on loopback hosts and refuses cross-site POSTs (DNS rebinding, CSRF-style form posts
  that could spend the live key). Two new tests, written failing first.
- Still open (should-fix/nits, not done): README:99 reference RU-03 cell says "n/a" but the file says 40; all-NULL
  numeric column chart rule (chart.py, D-42); bare 500 on DuckDB lock/IO errors; `svg_text` test helper does not
  unescape; route-level XSS test; no CSP for vendored htmx.

## Design pass 2026-11-18 (scheduled run, branch `design/impl`, `docs/design/RUN.md`)

Built from the Claude Design handoff in `docs/design/` (D-51..D-61), on top of `main` + `phase-4` (D-51):

- Pages: Ask (`/`: start state, answered, guard refusal, can't answer, query error, timeout, no draft, input errors,
  warehouse not built), `/eval` (committed run file), `/data` (the marts the model can see). Shared layout,
  `rollup/ui/static/rollup.css` tokens (light from the artboards, dark kept), no web fonts, no new library.
- Gap artboards added: `Start`, `CantAnswer`, `States`, `DataDocs` (`docs/design/*.dc.html`, in `canvas.json`).
- Three independent reviews (design, UX, accessibility); accepted findings fixed (D-61), PRD gained
  "Design, UX and accessibility requirements" DUX-01..DUX-12.
- Tests: `tests/test_ui_design.py`; `make a11y` (local axe-core + keyboard pass; not in CI, D-56).
- Left open: the first recorded question shows the fallback paragraph (UX-4); line-chart minimum label can overlap its
  point; chart is still `role="img"` with the table as its text alternative; fonts are system fonts (D-53).

Shane's hand steps for the design pass:
1. Open the Design canvas (https://claude.ai/artifact/XU4VftMnpiQmiDp1i8FABd) and add the four gap artboards if you
   want them there.
2. `make build && make ui`, look at `/`, `/eval`, `/data`; optionally `npm install --prefix /tmp/axe axe-core@4.10.2`
   and `make a11y AXE=/tmp/axe/node_modules/axe-core/axe.min.js`.
3. Review the design-pass PR (base `phase-4`, D-51); merge or not.

## What is left / not verified

- The UI has never been run against a live model. Nor has the eval since D-38/D-39 (whether D-39 fixes golden #20
  is still unknown).
- RU-03 does not detect numbers written as words (D-32).
- The UI is local and single-user: no auth, no deploy (D-46). Hosting it would need auth and a review of D-46 first.
- The PRD's Phases line ends at Phase 4; anything further needs a new PRD line from the owner.

## Owner hand steps

1. ~~Review and merge PR #6~~ (done 2026-11-18).
2. Locally: `pip install -e '.[dev]' && make build && make ui`, open http://127.0.0.1:8000, try a few recorded
   questions (e.g. "Delete all closed-lost opportunities older than a year." for a guard refusal).
3. Optional, with your own key: `pip install -e '.[live]'`, export `ANTHROPIC_API_KEY` and `ROLLUP_LLM_MODEL`, then
   `make ui MODEL=live`. Optionally `python -m rollup.eval.run --model live --out docs/eval/live-run.json` and commit
   the file if you want the live numbers in the case study.
4. Decide whether anything follows Phase 4; the PRD's Phases line ends here.
