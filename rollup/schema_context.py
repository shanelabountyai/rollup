"""Schema context for SQL drafting: the marts only, from the dbt manifest (PRD Text-to-SQL; Phase 3).

The model sees model and column descriptions for the allowlisted ``marts`` tables and nothing else: staging,
intermediate and source nodes are dropped here, and the guards refuse them again if a draft names them anyway.
Column types come from the built DuckDB file when a path is given (the manifest does not carry them).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rollup.guards import ALLOWED_SCHEMA, MART_TABLES

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "warehouse" / "target" / "manifest.json"


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    description: str
    data_type: str | None = None


@dataclass(frozen=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]

    @property
    def qualified(self) -> str:
        return f"{ALLOWED_SCHEMA}.{self.name}"


@dataclass(frozen=True)
class SchemaContext:
    tables: tuple[TableInfo, ...]

    @property
    def table_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.tables)

    def render(self) -> str:
        """Plain-text schema block for the prompt."""
        out: list[str] = []
        for t in self.tables:
            out.append(f"TABLE {t.qualified} -- {_one_line(t.description)}")
            for c in t.columns:
                typ = f" {c.data_type}" if c.data_type else ""
                out.append(f"  {c.name}{typ} -- {_one_line(c.description)}")
            out.append("")
        return "\n".join(out).rstrip() + "\n"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def default_manifest_path() -> Path:
    return Path(os.environ.get("ROLLUP_MANIFEST_PATH", DEFAULT_MANIFEST))


def context_from_manifest(
    manifest: dict[str, Any], column_types: dict[str, dict[str, str]] | None = None
) -> SchemaContext:
    """Keep only dbt models materialised in the ``marts`` schema whose name is allowlisted."""
    tables: list[TableInfo] = []
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "model" or node.get("schema") != ALLOWED_SCHEMA:
            continue
        name = node.get("name", "")
        if name not in MART_TABLES:
            continue
        types = (column_types or {}).get(name, {})
        cols = tuple(
            ColumnInfo(name=c["name"], description=c.get("description", "") or "", data_type=types.get(c["name"]))
            for c in node.get("columns", {}).values()
        )
        tables.append(TableInfo(name=name, description=node.get("description", "") or "", columns=cols))
    tables.sort(key=lambda t: t.name)
    return SchemaContext(tables=tuple(tables))


def _column_types(db_path: Path) -> dict[str, dict[str, str]]:
    # Trusted code reading the catalog, not a model draft, so it does not go through the guards.
    from rollup.runner import open_readonly

    con = open_readonly(db_path)
    try:
        rows = con.execute(
            "select table_name, column_name, data_type from information_schema.columns where table_schema = ?",
            [ALLOWED_SCHEMA],
        ).fetchall()
    finally:
        con.close()
    out: dict[str, dict[str, str]] = {}
    for table, column, dtype in rows:
        out.setdefault(str(table), {})[str(column)] = str(dtype)
    return out


def load_context(manifest_path: Path | str | None = None, db_path: Path | str | None = None) -> SchemaContext:
    path = Path(manifest_path) if manifest_path is not None else default_manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `make build` first")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    types = _column_types(Path(db_path)) if db_path is not None else None
    ctx = context_from_manifest(manifest, types)
    missing = MART_TABLES - ctx.table_names
    if missing:
        raise ValueError(f"manifest is missing allowlisted marts: {sorted(missing)}")
    return ctx
