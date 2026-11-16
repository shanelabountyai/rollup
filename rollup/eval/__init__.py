"""Golden-set eval (PRD "Eval"; Phase 3).

40 golden questions with hand-written reference SQL (``golden/NN_slug.sql``) and a refusal set of questions the
marts cannot answer (``refusals.json``). A draft scores when its result set is equivalent to the reference result
set (``equivalence.results_equivalent``, D-33) — SQL text is never compared. A refusal-set question scores when the
pipeline shows no numbers for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_DIR = EVAL_DIR / "golden"
REFUSALS_PATH = EVAL_DIR / "refusals.json"


@dataclass(frozen=True)
class GoldenQuestion:
    id: str  # file stem, e.g. "01_spend_by_platform"
    question: str
    ordered: bool  # row order is part of the answer (ranked / date-ordered questions)
    sql: str


@dataclass(frozen=True)
class RefusalQuestion:
    id: str
    question: str
    why: str


def load_golden(directory: Path = GOLDEN_DIR) -> list[GoldenQuestion]:
    out: list[GoldenQuestion] = []
    for path in sorted(directory.glob("*.sql")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) < 3 or not lines[0].startswith("-- Q:") or not lines[1].startswith("-- ordered:"):
            raise ValueError(f"{path.name} must start with '-- Q:' and '-- ordered:' lines")
        ordered = lines[1].removeprefix("-- ordered:").strip().lower()
        if ordered not in {"true", "false"}:
            raise ValueError(f"{path.name}: ordered must be true or false")
        out.append(
            GoldenQuestion(
                id=path.stem,
                question=lines[0].removeprefix("-- Q:").strip(),
                ordered=ordered == "true",
                sql="\n".join(lines[2:]).strip() + "\n",
            )
        )
    return out


def load_refusals(path: Path = REFUSALS_PATH) -> list[RefusalQuestion]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [RefusalQuestion(id=r["id"], question=r["question"], why=r["why"]) for r in data]
