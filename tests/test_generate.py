"""RU-04: data generation is seeded and reproducible."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from rollup.generate import END_DATE, START_DATE, TABLES, generate, write_parquet


def test_same_seed_same_bytes(tmp_path: Path) -> None:
    a = write_parquet(generate(27), tmp_path / "a")
    b = write_parquet(generate(27), tmp_path / "b")
    assert a == b
    assert set(a) == set(TABLES)


def test_different_seed_differs(tmp_path: Path) -> None:
    a = write_parquet(generate(27), tmp_path / "a")
    b = write_parquet(generate(28), tmp_path / "b")
    assert a["campaigns"] == b["campaigns"]  # static catalogue
    assert a["web_sessions"] != b["web_sessions"]
    assert a["crm_leads"] != b["crm_leads"]


def test_all_tables_present_and_nonempty(tables: dict[str, pd.DataFrame]) -> None:
    for name in TABLES:
        assert len(tables[name]) > 0, name


def test_date_range_is_18_months(tables: dict[str, pd.DataFrame]) -> None:
    d = pd.to_datetime(tables["ad_spend"]["report_date"])
    assert d.min().date() == START_DATE
    assert d.max().date() == END_DATE
    assert (END_DATE - START_DATE).days + 1 == 548


def test_three_platforms(tables: dict[str, pd.DataFrame]) -> None:
    assert set(tables["ad_spend"]["platform"]) == {"google_ads", "linkedin_ads", "meta_ads"}


def test_primary_keys_unique(tables: dict[str, pd.DataFrame]) -> None:
    keys = {
        "campaigns": "campaign_id",
        "web_sessions": "session_id",
        "form_fills": "form_fill_id",
        "crm_contacts": "contact_id",
        "crm_leads": "lead_id",
        "crm_opportunities": "opportunity_id",
        "crm_opportunity_stage_history": "stage_history_id",
    }
    for t, k in keys.items():
        assert tables[t][k].is_unique, t
    assert tables["crm_contacts"]["email"].is_unique
