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
