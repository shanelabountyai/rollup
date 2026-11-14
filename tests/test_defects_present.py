"""Each injected defect is really in the raw data (so the dbt tests have work to do)."""

from __future__ import annotations

import pandas as pd

from rollup.defects import DEFECTS, DUPLICATE_LEAD_RATE, RENAME_DATE, RENAMED_CAMPAIGN_ID
from rollup.generate import LOCAL_TZ


def test_catalogue_covers_four_defects() -> None:
    assert [d.code for d in DEFECTS] == ["D1", "D2", "D3", "D4"]


def test_d1_utm_casing_drift(tables: dict[str, pd.DataFrame]) -> None:
    s = tables["web_sessions"]["utm_source"].dropna()
    drifted = s[s != s.str.strip().str.lower()]
    assert len(drifted) / len(s) > 0.2
    assert s.str.strip().str.lower().nunique() < s.nunique()


def test_d2_duplicate_leads(tables: dict[str, pd.DataFrame]) -> None:
    leads = tables["crm_leads"]
    raw_unique = leads["email"].nunique()
    norm_unique = leads["email"].str.strip().str.lower().nunique()
    dup_share = (len(leads) - norm_unique) / norm_unique
    assert raw_unique == len(leads)  # exact-match dedupe finds nothing...
    assert abs(dup_share - DUPLICATE_LEAD_RATE) < 0.02  # ...but ~6% are duplicates


def test_d3_timezone_mismatch(tables: dict[str, pd.DataFrame]) -> None:
    f = tables["form_fills"].merge(tables["web_sessions"][["session_id", "session_start"]], on="session_id")
    naive_early = (f["submitted_at"] < f["session_start"]).mean()
    assert naive_early > 0.95  # read naively, fills precede their session
    utc = pd.DatetimeIndex(f["submitted_at"]).tz_localize(LOCAL_TZ).tz_convert("UTC").tz_localize(None)
    assert (utc >= pd.DatetimeIndex(f["session_start"])).all()


def test_d4_renamed_campaign(tables: dict[str, pd.DataFrame]) -> None:
    spend = tables["ad_spend"]
    rows = spend[spend["campaign_id"] == RENAMED_CAMPAIGN_ID]
    assert rows["campaign_name"].nunique() == 2
    before = rows[pd.to_datetime(rows["report_date"]) < pd.Timestamp(RENAME_DATE)]["campaign_name"]
    catalogue = tables["campaigns"].set_index("campaign_id").loc[RENAMED_CAMPAIGN_ID, "campaign_name"]
    assert catalogue not in set(before)
