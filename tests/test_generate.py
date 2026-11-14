"""RU-04: data generation is seeded and reproducible."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from rollup.generate import END_DATE, LOCAL_TZ, START_DATE, TABLES, generate, write_parquet


def test_same_seed_same_bytes(tmp_path: Path) -> None:
    a = write_parquet(generate(27), tmp_path / "a")
    b = write_parquet(generate(27), tmp_path / "b")
    assert a == b
    assert set(a) == set(TABLES)


# D-19: sha256 of each Parquet file for seed 27, with the exact numpy / pandas / pyarrow pins
# in pyproject.toml (D-14). A dependency bump or a generator change that moves these must
# update them in the same commit and say why.
GOLDEN_SEED_27 = {
    "campaigns": "bdf46ef2a6423e5abf9866bf9b6777ee430d5305e05ad3bda421b28d837c9f2c",
    "ad_spend": "1113f5d31ca8f9a29499e5bb0339bc076267e2619cce958fe15fe6aa9c50963c",
    "web_sessions": "0f411df904b2002881a140f5354325bf21c9320779dab64d260ffc7e1a6ef35b",
    "form_fills": "189d25f3e47854f7ade47c6fbf9f649d06c50ae4e7ab9496d4212165886e4db3",
    "crm_contacts": "9dcddcede11e8332b4e461907a0705fef82c79a2f359fbb66fcaaec8bf93ea49",
    "crm_leads": "c9482f21814eed9652e9350228ae007d53da5a37584db16a23acaa33c21e9b34",
    "crm_opportunities": "55ab3ec8b32284db47a2a7c2a68e5039521e64dfd5c5b132f66662931ed42838",
    "crm_opportunity_stage_history": "79fbfbc446ec02967d21e5168f5cddd620d294e7e0808155c2963171110a6e2e",
}


def test_seed_27_matches_golden_hashes(tmp_path: Path) -> None:
    assert write_parquet(generate(27), tmp_path) == GOLDEN_SEED_27


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


def test_close_date_is_local_day_of_close(tables: dict[str, pd.DataFrame]) -> None:
    """D-15: close_date is the America/New_York day the closing stage was entered (UTC timestamp)."""
    opps = tables["crm_opportunities"]
    hist = tables["crm_opportunity_stage_history"]
    closing = hist[hist["stage"].isin(["closed_won", "closed_lost"])]
    m = opps[opps["is_closed"]].merge(closing, on="opportunity_id")
    assert len(m) == opps["is_closed"].sum()
    local = pd.DatetimeIndex(m["entered_at"]).tz_localize("UTC").tz_convert(LOCAL_TZ).date
    assert (m["close_date"].to_numpy() == local).all()
    utc = pd.DatetimeIndex(m["entered_at"]).date
    assert (m["close_date"].to_numpy() != utc).any()  # the UTC day would differ for evening closes
