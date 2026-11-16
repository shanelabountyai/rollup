"""Hand-written SQL against the marts (Phase 2). Each file starts with a ``-- Q:`` line stating the question."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

QUERY_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class NamedQuery:
    name: str
    question: str
    sql: str


def load_queries() -> dict[str, NamedQuery]:
    """All hand-written queries, keyed by file stem, in name order."""
    out: dict[str, NamedQuery] = {}
    for path in sorted(QUERY_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        if not first.startswith("-- Q:"):
            raise ValueError(f"{path.name} must start with a '-- Q:' question line")
        out[path.stem] = NamedQuery(name=path.stem, question=first.removeprefix("-- Q:").strip(), sql=text)
    return out
