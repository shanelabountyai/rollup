"""Run the golden-set eval and write a run file (``make eval``; D-35).

    python -m rollup.eval.run                      # recorded drafts (default; offline, no key)
    python -m rollup.eval.run --model reference    # harness check: drafts the reference SQL, must score 40/40
    python -m rollup.eval.run --model live         # owner hand step: needs ANTHROPIC_API_KEY + ROLLUP_LLM_MODEL

The run file is JSON (schema ``rollup.eval.run/v1``) that Yardstick (#26) reads. Exit code 1 if any pipeline
invariant broke: a refused question showed a digit, a shown answer failed RU-03, or the DB file changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from rollup.ask import AskResult, ask
from rollup.eval import GoldenQuestion, RefusalQuestion, load_golden, load_refusals
from rollup.eval.equivalence import results_equivalent
from rollup.llm import DraftModel, ModelUnavailable, RecordedModel, ReferenceModel
from rollup.runner import default_db_path, execute_guarded, open_readonly
from rollup.schema_context import SchemaContext, load_context
from rollup.validator import validate_answer

RUN_SCHEMA = "rollup.eval.run/v1"
DEFAULT_OUT = Path("data") / "eval" / "run.json"


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | float | str):
        return v
    return str(v)


def _invariant_failures(r: AskResult) -> list[str]:
    out: list[str] = []
    if r.answered:
        if not validate_answer(r.answer, r.columns, r.rows).ok:
            out.append("RU-03: shown answer has a number not in the result")
    else:
        if re.search(r"\d", r.answer):
            out.append("refusal shows a number")
        if r.rows or r.executed_sql:
            out.append("refusal carries an executed result")
    if r.status == "refused_guard" and r.executed_sql:
        out.append("guard-refused draft has executed SQL")
    return out


def _item(kind: str, qid: str, r: AskResult) -> dict[str, Any]:
    return {
        "set": kind,
        "id": qid,
        "question": r.question,
        "status": r.status,
        "guard_code": r.guard_code,
        "reason": r.reason,
        "draft_sql": r.draft_sql,
        "executed_sql": r.executed_sql,
        "columns": r.columns,
        "row_count": len(r.rows),
        "truncated": r.truncated,
        "answer": r.answer,
        "answer_source": r.answer_source,
        "model_answer": r.model_answer,
        "model_answer_violations": r.validation.violations if r.validation else [],
        "elapsed_ms": None if r.elapsed_ms is None else round(r.elapsed_ms, 1),
        "invariant_failures": _invariant_failures(r),
    }


def run_eval(
    model: DraftModel,
    con: duckdb.DuckDBPyConnection,
    context: SchemaContext,
    golden: Sequence[GoldenQuestion],
    refusals: Sequence[RefusalQuestion],
    *,
    drafts: str,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for g in golden:
        ref = execute_guarded(con, g.sql)  # reference SQL goes through the same guards
        r = ask(g.question, model, con, context)
        it = _item("golden", g.id, r)
        it["ordered"] = g.ordered
        it["reference_row_count"] = len(ref.rows)
        it["equivalent"] = r.answered and results_equivalent(ref.rows, r.rows, ordered=g.ordered)
        items.append(it)
    for q in refusals:
        r = ask(q.question, model, con, context)
        it = _item("refusal", q.id, r)
        it["correct"] = not r.answered
        items.append(it)

    gold = [i for i in items if i["set"] == "golden"]
    refs = [i for i in items if i["set"] == "refusal"]
    answered = [i for i in items if i["status"] == "answered"]
    eq = sum(1 for i in gold if i["equivalent"])
    summary = {
        "golden_total": len(gold),
        "golden_equivalent": eq,
        "golden_score": round(eq / len(gold), 4) if gold else None,
        "golden_status_counts": dict(sorted(Counter(i["status"] for i in gold).items())),
        "refusal_total": len(refs),
        "refusal_correct": sum(1 for i in refs if i["correct"]),
        "refusal_status_counts": dict(sorted(Counter(i["status"] for i in refs).items())),
        "answers_shown": len(answered),
        "answers_from_model": sum(1 for i in answered if i["answer_source"] == "model"),
        "answers_from_fallback": sum(1 for i in answered if i["answer_source"] == "fallback"),
        "model_paragraphs_rejected_ru03": sum(1 for i in answered if i["model_answer_violations"]),
        "guard_refusals_by_code": dict(
            sorted(Counter(i["guard_code"] for i in items if i["status"] == "refused_guard").items())
        ),
        "invariant_failures": sum(len(i["invariant_failures"]) for i in items),
    }
    return {
        "schema": RUN_SCHEMA,
        "project": "rollup",
        "model": model.name,
        "drafts": drafts,
        "note": (
            "Scores measure the pipeline on recorded drafts, not a live model."
            if drafts == "recorded"
            else ("Reference SQL drafted; harness check only." if drafts == "reference" else "Live model drafts.")
        ),
        "summary": summary,
        "items": items,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rollup.eval.run", description="Run the Rollup golden-set eval.")
    p.add_argument("--model", choices=["recorded", "reference", "live"], default="recorded")
    p.add_argument("--recording", default=None, help="recorded responses JSON (default: rollup/eval/recorded.json)")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--db", default=None)
    p.add_argument("--manifest", default=None)
    args = p.parse_args(argv)

    golden, refusals = load_golden(), load_refusals()
    model: DraftModel
    if args.model == "reference":
        model = ReferenceModel({g.question: g.sql for g in golden})
    elif args.model == "live":
        from rollup.llm import AnthropicModel

        try:
            model = AnthropicModel()
        except ModelUnavailable as e:
            print(f"live model unavailable: {e}", file=sys.stderr)
            return 2
    else:
        model = RecordedModel(args.recording) if args.recording else RecordedModel()

    db = Path(args.db) if args.db else default_db_path()
    before = _sha256(db)
    con = open_readonly(db)
    try:
        run = run_eval(model, con, load_context(args.manifest, db), golden, refusals, drafts=args.model)
    finally:
        con.close()
    db_unchanged = _sha256(db) == before
    run["summary"]["db_unchanged"] = db_unchanged

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(run, indent=2, default=_jsonable) + "\n", encoding="utf-8")
    s = run["summary"]
    print(f"model: {run['model']} ({run['drafts']} drafts) -> {out}")
    print(
        f"golden: {s['golden_equivalent']}/{s['golden_total']} equivalent ({s['golden_score']:.1%})  "
        f"statuses {s['golden_status_counts']}"
    )
    print(
        f"refusal set: {s['refusal_correct']}/{s['refusal_total']} correctly showed no numbers  "
        f"statuses {s['refusal_status_counts']}"
    )
    print(
        f"answers shown: {s['answers_shown']} (model {s['answers_from_model']}, fallback "
        f"{s['answers_from_fallback']}); model paragraphs rejected by RU-03: {s['model_paragraphs_rejected_ru03']}"
    )
    print(
        f"guard refusals: {s['guard_refusals_by_code']}; invariant failures: {s['invariant_failures']}; "
        f"db unchanged: {db_unchanged}"
    )
    if run["drafts"] == "recorded":
        print("note: these numbers measure the pipeline on recorded drafts, not a live model")
    return 0 if s["invariant_failures"] == 0 and db_unchanged else 1


if __name__ == "__main__":
    sys.exit(main())
