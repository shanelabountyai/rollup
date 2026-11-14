# #27 Rollup — marketing warehouse + safe text-to-SQL — Claude Code kickoff

## Session prompt — Phase 1

```text
You are building Rollup (build-log #27). Repo shanelabountyai/rollup; main holds docs/PRD.md and docs/DECISIONS.md
(copied from this kit). Read both. Decisions are in force; new ones: pick, append a row, keep going, never ask.

Phase 1 only (branch kickoff, PR #1 unmerged): write docs/PHASE1_PLAN.md first and open the PR. Then: seeded
synthetic data generator (Python, writes Parquet), dbt-duckdb project with staging/intermediate/marts per the PRD,
dbt tests on every model plus custom tests that catch each injected defect, `make build` runs generate + dbt build.
CI: ruff, mypy, pytest, dbt build. Gate: dbt build green, RU-04 and RU-05 green, `dbt docs generate` succeeds.
PR body: models built, test counts, decisions added. Then stop.
```
