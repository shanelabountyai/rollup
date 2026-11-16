"""Drafting context is the marts only, from the dbt manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from rollup.guards import MART_TABLES
from rollup.schema_context import context_from_manifest, load_context

FAKE_MANIFEST = {
    "nodes": {
        "model.rollup.fct_spend": {
            "resource_type": "model",
            "schema": "marts",
            "name": "fct_spend",
            "description": "Spend.",
            "columns": {"spend_usd": {"name": "spend_usd", "description": "USD."}},
        },
        "model.rollup.stg_ad_spend": {
            "resource_type": "model",
            "schema": "staging",
            "name": "stg_ad_spend",
            "description": "raw",
            "columns": {},
        },
        "model.rollup.int_campaign_map": {
            "resource_type": "model",
            "schema": "intermediate",
            "name": "int_campaign_map",
            "description": "",
            "columns": {},
        },
        "model.rollup.marts_scratch": {
            "resource_type": "model",
            "schema": "marts",
            "name": "marts_scratch",
            "description": "not allowlisted",
            "columns": {},
        },
        "test.rollup.x": {"resource_type": "test", "schema": "marts", "name": "fct_touches", "columns": {}},
    }
}


def test_context_keeps_only_allowlisted_mart_models() -> None:
    ctx = context_from_manifest(FAKE_MANIFEST, {"fct_spend": {"spend_usd": "DECIMAL(12,2)"}})
    assert ctx.table_names == {"fct_spend"}
    text = ctx.render()
    assert "TABLE marts.fct_spend -- Spend." in text and "spend_usd DECIMAL(12,2) -- USD." in text
    for hidden in ("stg_ad_spend", "int_campaign_map", "marts_scratch", "staging", "intermediate"):
        assert hidden not in text


def test_missing_manifest_says_to_build(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="make build"):
        load_context(tmp_path / "nope.json")


@pytest.mark.warehouse
def test_real_context_is_exactly_the_marts(warehouse_db: Path, repo_root: Path) -> None:
    ctx = load_context(repo_root / "warehouse" / "target" / "manifest.json", warehouse_db)
    assert ctx.table_names == MART_TABLES
    text = ctx.render()
    for t in ctx.tables:
        assert t.description.strip()
        assert t.columns
        for c in t.columns:
            assert c.description.strip(), f"{t.name}.{c.name} has no description"
            assert c.data_type, f"{t.name}.{c.name} has no type"
    for hidden in ("stg_", "int_", "staging.", "intermediate.", "raw_", "information_schema"):
        assert hidden not in text
