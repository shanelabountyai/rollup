# Design handoff

Source of truth for the UI built on branch `design/impl`. Exported 2026-11-18 from the Claude Design canvas so cloud runs don't depend on artifact access.

- Canvas: https://claude.ai/artifact/XU4VftMnpiQmiDp1i8FABd
- Brief: https://claude.ai/artifact/G7rMUD716MHRiTqujsxtmr

## Artboards (`docs/design/*.dc.html`)

Each file is a self-contained Design Component: HTML with inline styles, `{{holes}}` filled by the `renderVals()` script at the bottom. Read the markup and the script together; the script holds the sample data.

| File | Screen | Frame |
| --- | --- | --- |
| `Main.dc.html` | Ask — question to traced answer | 1280×1720 |
| `Refusal.dc.html` | Refusal — a guard said no | 1280×820 |
| `Eval.dc.html` | Eval — 40 golden questions (public) | 1280×1120 |

## Owner calls (binding)

- First touch is the primary attribution model for funnel and CAC; last touch is a second column. (Shane, 2026-11-14)
- Brief open questions not answered by Shane; the design took the recommendations: keep FastAPI + HTMX (D-03), chart type fixed by result shape in code, eval page public. Record as DECISIONS rows.

## Gaps: screens the PRD needs that no artboard covers

- Starter-question empty state
- 'Data can't answer' refusal variant (shown only as a note on the Refusal artboard)

Design each gap as a new `docs/design/<Name>.dc.html` in the same look before building it.

Gap designs added by the design implementation run (2026-11-18), in `canvas.json` boards/order but not yet on the
Claude Design canvas:

| File | Covers |
| --- | --- |
| `Start.dc.html` | Starter-question empty state (HANDOFF gap 1), the "what happens when you ask" steps, all recorded questions |
| `CantAnswer.dc.html` | 'Data can't answer' refusal (HANDOFF gap 2, `refused_question`), with the marts it does cover |
| `States.dc.html` | Gaps found in the code: `query_error`, `timeout`, `model_error`, the answer card when RU-03 replaced the model's paragraph, no-chart reason, empty/too-long input, loading, warehouse not built |
| `DataDocs.dc.html` | The "Data docs" nav link on Main: the marts and their dbt descriptions (the drafting context) |

Status colours (word → glyph → colour): ✓ passed / pass (blue `#1D4F91` on `#E6EEF9`); ✕ refused / fail /
error (`#7A2509` on `#FCE6DD`); ◆ can't answer, no draft, correctly refused (neutral or blue info); ▲ replaced
by the validator (`#5C3D00` on `#FBF0D5`); – not reached (`#565B66`).

## Placeholders

Every number on the Ask and Eval artboards is illustrative ([NN], [DATE], the CAC table); show only real result-set values.
