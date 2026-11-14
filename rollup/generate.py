"""Seeded synthetic data generator for Rollup (RU-04: seeded and reproducible).

Writes Parquet files for a fictional B2B company over 18 months:
ad spend (3 platforms), web sessions with UTMs, form fills, CRM contacts / leads /
opportunities / stage history — plus the injected defects in :mod:`rollup.defects`.

Nothing here reads the wall clock or any global RNG: same seed -> same bytes.

Usage::

    python -m rollup.generate --seed 27 --out data/raw
"""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from rollup.defects import DUPLICATE_LEAD_RATE, RENAME_DATE, RENAMED_CAMPAIGN_ID

DEFAULT_SEED = 27
START_DATE = date(2025, 5, 1)
N_DAYS = 548  # ~18 months
END_DATE = START_DATE + timedelta(days=N_DAYS - 1)
LOCAL_TZ = "America/New_York"

TABLES = (
    "campaigns",
    "ad_spend",
    "web_sessions",
    "form_fills",
    "crm_contacts",
    "crm_leads",
    "crm_opportunities",
    "crm_opportunity_stage_history",
)


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    platform: str
    name: str
    start_day: int
    end_day: int  # exclusive
    daily_budget: float
    objective: str


PLATFORM_CPC = {"google_ads": 6.0, "linkedin_ads": 9.5, "meta_ads": 2.6}
PLATFORM_CPM = {"google_ads": 45.0, "linkedin_ads": 70.0, "meta_ads": 14.0}
PLATFORM_UTM = {
    "google_ads": ("google", "cpc"),
    "linkedin_ads": ("linkedin", "paid_social"),
    "meta_ads": ("facebook", "paid_social"),
}

OLD_RENAMED_NAME = "ABM Enterprise Q3 2025"
NEW_RENAMED_NAME = "ABM Enterprise Always-On"

CAMPAIGNS: tuple[Campaign, ...] = (
    Campaign("gads_1001", "google_ads", "Brand Search", 0, N_DAYS, 180, "conversions"),
    Campaign("gads_1002", "google_ads", "Competitor Conquest", 0, N_DAYS, 220, "conversions"),
    Campaign("gads_1003", "google_ads", "Nonbrand Attribution Software", 0, N_DAYS, 300, "conversions"),
    Campaign("gads_1004", "google_ads", "Nonbrand Pipeline Analytics", 60, N_DAYS, 250, "conversions"),
    Campaign("gads_1005", "google_ads", "Retargeting Display", 30, 400, 90, "traffic"),
    Campaign("gads_1006", "google_ads", "Webinar Search Q1 2026", 245, 335, 140, "conversions"),
    Campaign("li_2001", "linkedin_ads", OLD_RENAMED_NAME, 0, N_DAYS, 260, "lead_generation"),
    Campaign("li_2002", "linkedin_ads", "CMO Thought Leadership", 0, 300, 150, "awareness"),
    Campaign("li_2003", "linkedin_ads", "Ops Persona Lead Gen", 20, N_DAYS, 230, "lead_generation"),
    Campaign("li_2004", "linkedin_ads", "Webinar Promo", 240, 340, 120, "lead_generation"),
    Campaign("li_2005", "linkedin_ads", "Retargeting Website Visitors", 90, N_DAYS, 80, "traffic"),
    Campaign("li_2006", "linkedin_ads", "Mid-Market Demo Offer", 300, N_DAYS, 200, "lead_generation"),
    Campaign("meta_3001", "meta_ads", "Lookalike Customers", 0, N_DAYS, 110, "conversions"),
    Campaign("meta_3002", "meta_ads", "Retargeting Video", 45, N_DAYS, 60, "traffic"),
    Campaign("meta_3003", "meta_ads", "Ebook Benchmark Report", 100, 420, 130, "lead_generation"),
    Campaign("meta_3004", "meta_ads", "Webinar Promo Meta", 240, 340, 70, "lead_generation"),
    Campaign("meta_3005", "meta_ads", "Brand Awareness Video", 0, 200, 90, "awareness"),
    Campaign("meta_3006", "meta_ads", "Holiday Promo 2025", 200, 245, 150, "conversions"),
)

# Probability that a session on this channel produces a form fill.
FILL_RATE = {
    "paid_search": 0.030,
    "paid_social": 0.016,
    "organic_search": 0.020,
    "email": 0.025,
    "direct": 0.012,
    "referral": 0.035,
}
# Relative likelihood a person becomes an opportunity, by converting channel.
OPP_RATE = {
    "paid_search": 0.20,
    "paid_social": 0.13,
    "organic_search": 0.18,
    "email": 0.16,
    "direct": 0.22,
    "referral": 0.26,
}
NONPAID_DAILY = {"organic_search": 260.0, "direct": 140.0, "email": 60.0, "referral": 45.0}

FIRST_NAMES = np.array(
    [
        "ava",
        "ben",
        "chloe",
        "dan",
        "ella",
        "finn",
        "grace",
        "hugo",
        "isla",
        "jack",
        "kai",
        "leah",
        "max",
        "nina",
        "omar",
        "priya",
        "quinn",
        "ravi",
        "sara",
        "tom",
        "uma",
        "vic",
        "will",
        "xena",
        "yusuf",
        "zoe",
    ]
)
LAST_NAMES = np.array(
    [
        "adams",
        "baker",
        "chen",
        "diaz",
        "evans",
        "fox",
        "garcia",
        "hall",
        "ito",
        "jones",
        "khan",
        "lopez",
        "moore",
        "ng",
        "ortiz",
        "patel",
        "quist",
        "rossi",
        "smith",
        "tran",
        "usman",
        "vega",
        "wong",
        "xu",
        "young",
        "zhang",
    ]
)
COMPANY_WORDS = np.array(
    [
        "acme",
        "apex",
        "beacon",
        "cobalt",
        "delta",
        "ember",
        "fathom",
        "granite",
        "harbor",
        "ion",
        "juniper",
        "kestrel",
        "lumen",
        "meridian",
        "northwind",
        "orbit",
        "pioneer",
        "quarry",
        "ridge",
        "summit",
        "tidal",
        "umbra",
        "vertex",
        "willow",
    ]
)
COMPANY_SUFFIX = np.array(["labs", "systems", "group", "analytics", "cloud", "health", "logistics"])
TITLES = np.array(
    [
        "Marketing Ops Manager",
        "VP Marketing",
        "CMO",
        "Demand Gen Lead",
        "RevOps Analyst",
        "Director of Growth",
        "Head of Sales Ops",
        "Marketing Analyst",
    ]
)
LANDING_PAGES = np.array(
    [
        "/",
        "/pricing",
        "/demo",
        "/blog/attribution-101",
        "/ebook/benchmarks",
        "/webinar",
        "/product/pipeline",
        "/customers",
    ]
)
FORM_FOR_PAGE = {
    "/": "contact_us",
    "/pricing": "demo_request",
    "/demo": "demo_request",
    "/blog/attribution-101": "newsletter_signup",
    "/ebook/benchmarks": "ebook_download",
    "/webinar": "webinar_registration",
    "/product/pipeline": "demo_request",
    "/customers": "contact_us",
}
STAGES = ("prospecting", "discovery", "proposal", "negotiation")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def campaign_name_on(c: Campaign, day: date) -> str:
    """D4: the renamed campaign carries its old name before RENAME_DATE."""
    if c.campaign_id == RENAMED_CAMPAIGN_ID and day >= date.fromisoformat(RENAME_DATE):
        return NEW_RENAMED_NAME
    return c.name


def platform_channel(platform: str) -> str:
    return "paid_search" if platform == "google_ads" else "paid_social"


def _drift_case(rng: np.random.Generator, values: np.ndarray, rate: float = 0.35) -> np.ndarray:
    """D1: apply random casing / whitespace drift to a share of string values."""
    out = values.astype(object).copy()
    mask = np.array([v is not None for v in out]) & (rng.random(len(out)) < rate)
    styles = rng.integers(0, 4, size=len(out))
    for i in np.flatnonzero(mask):
        v = str(out[i])
        s = styles[i]
        if s == 0:
            out[i] = v.upper()
        elif s == 1:
            out[i] = v.title()
        elif s == 2:
            out[i] = f" {v}"
        else:
            out[i] = f"{v.capitalize()} "
    return out


def build_campaigns() -> pd.DataFrame:
    rows = []
    for c in CAMPAIGNS:
        rows.append(
            {
                "campaign_id": c.campaign_id,
                "platform": c.platform,
                # platform catalogue is a snapshot "as of today" -> current name only
                "campaign_name": campaign_name_on(c, END_DATE),
                "objective": c.objective,
                "start_date": START_DATE + timedelta(days=c.start_day),
                "end_date": (START_DATE + timedelta(days=c.end_day - 1)) if c.end_day < N_DAYS else None,
                "daily_budget_usd": float(c.daily_budget),
            }
        )
    return pd.DataFrame(rows)


def build_ad_spend(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for c in CAMPAIGNS:
        days = np.arange(c.start_day, c.end_day)
        dates = [START_DATE + timedelta(days=int(d)) for d in days]
        weekday = np.array([d.weekday() for d in dates])
        factor = np.where(weekday >= 5, 0.6, 1.0)
        noise = rng.lognormal(0.0, 0.25, size=len(days))
        spend = np.round(c.daily_budget * factor * noise, 2)
        cpm = PLATFORM_CPM[c.platform] * rng.lognormal(0.0, 0.15, size=len(days))
        impressions = np.maximum((spend / cpm * 1000).astype(np.int64), 1)
        cpc = PLATFORM_CPC[c.platform] * rng.lognormal(0.0, 0.2, size=len(days))
        clicks = np.minimum((spend / cpc).astype(np.int64), impressions)
        for i, d in enumerate(dates):
            rows.append(
                {
                    "platform": c.platform,
                    "campaign_id": c.campaign_id,
                    "campaign_name": campaign_name_on(c, d),
                    "report_date": d,
                    "spend_usd": float(spend[i]),
                    "impressions": int(impressions[i]),
                    "clicks": int(clicks[i]),
                }
            )
    df = pd.DataFrame(rows)
    return df.sort_values(["report_date", "campaign_id"], kind="stable").reset_index(drop=True)


def _local_times_to_utc(rng: np.random.Generator, day_index: np.ndarray) -> pd.Series:
    """Session start in UTC. Local hours 07:00-22:59 never hit a DST gap/overlap."""
    hours = rng.choice(
        np.arange(7, 23),
        size=len(day_index),
        p=np.array([2, 4, 6, 8, 8, 7, 8, 8, 7, 6, 5, 4, 3, 3, 2, 1], dtype=float) / 82,
    )
    seconds = rng.integers(0, 3600, size=len(day_index))
    base = pd.Timestamp(START_DATE)
    local = (
        base
        + pd.to_timedelta(day_index, unit="D")
        + pd.to_timedelta(hours, unit="h")
        + pd.to_timedelta(seconds, unit="s")
    )
    utc = pd.DatetimeIndex(local).tz_localize(LOCAL_TZ).tz_convert("UTC").tz_localize(None)
    return pd.Series(utc.astype("datetime64[us]"))


def build_sessions(rng: np.random.Generator, spend: pd.DataFrame) -> pd.DataFrame:
    # Paid sessions: driven by clicks per campaign-day.
    n_paid = rng.poisson(spend["clicks"].to_numpy() * 0.8)
    rep = spend.loc[spend.index.repeat(n_paid)].reset_index(drop=True)
    paid = pd.DataFrame(
        {
            "day_index": (pd.to_datetime(rep["report_date"]) - pd.Timestamp(START_DATE)).dt.days.to_numpy(),
            "channel": rep["platform"].map(platform_channel).to_numpy(),
            "utm_source": rep["platform"].map(lambda p: PLATFORM_UTM[p][0]).to_numpy(),
            "utm_medium": rep["platform"].map(lambda p: PLATFORM_UTM[p][1]).to_numpy(),
            "utm_campaign": rep["campaign_name"].map(slugify).to_numpy(),
            "referrer_domain": None,
        }
    )
    # Non-paid sessions, with gentle growth and weekday seasonality.
    parts = [paid]
    days = np.arange(N_DAYS)
    weekday = np.array([(START_DATE + timedelta(days=int(d))).weekday() for d in days])
    growth = 1.0 + 0.5 * days / N_DAYS
    for channel, base in NONPAID_DAILY.items():
        lam = base * growth * np.where(weekday >= 5, 0.55, 1.0)
        n = rng.poisson(lam)
        di = np.repeat(days, n)
        k = len(di)
        if channel == "email":
            month = [(START_DATE + timedelta(days=int(d))).strftime("%Y-%m") for d in di]
            src = np.full(k, "hubspot", dtype=object)
            med = np.full(k, "email", dtype=object)
            camp = np.array([f"newsletter-{m}" for m in month], dtype=object)
            ref = np.full(k, None, dtype=object)
        else:
            src = med = camp = np.full(k, None, dtype=object)
            if channel == "organic_search":
                ref = rng.choice(
                    np.array(["google.com", "bing.com", "duckduckgo.com"]), size=k, p=[0.85, 0.1, 0.05]
                ).astype(object)
            elif channel == "referral":
                ref = rng.choice(np.array(["g2.com", "capterra.com", "partner.example.com"]), size=k).astype(object)
            else:
                ref = np.full(k, None, dtype=object)
        parts.append(
            pd.DataFrame(
                {
                    "day_index": di,
                    "channel": channel,
                    "utm_source": src,
                    "utm_medium": med,
                    "utm_campaign": camp,
                    "referrer_domain": ref,
                }
            )
        )
    s = pd.concat(parts, ignore_index=True)
    s["session_start"] = _local_times_to_utc(rng, s["day_index"].to_numpy())
    s = s.sort_values(["session_start", "channel", "utm_campaign"], kind="stable", na_position="first")
    s = s.reset_index(drop=True)
    n_sessions = len(s)
    # Returning visitors: pool smaller than sessions so people have multiple touches.
    s["anonymous_id"] = [f"anon_{i:07d}" for i in rng.integers(0, int(n_sessions * 0.55), size=n_sessions)]
    s["session_id"] = [f"sess_{i:08d}" for i in range(n_sessions)]
    s["landing_page"] = rng.choice(LANDING_PAGES, size=n_sessions)
    s["pageviews"] = 1 + rng.poisson(1.6, size=n_sessions)
    # D1: casing drift on UTMs.
    for col in ("utm_source", "utm_medium", "utm_campaign"):
        s[col] = _drift_case(rng, s[col].to_numpy())
    return s


def _person_identity(rng: np.random.Generator, anon_ids: np.ndarray) -> pd.DataFrame:
    k = len(anon_ids)
    first = rng.choice(FIRST_NAMES, size=k)
    last = rng.choice(LAST_NAMES, size=k)
    co = [
        f"{a}-{b}" for a, b in zip(rng.choice(COMPANY_WORDS, size=k), rng.choice(COMPANY_SUFFIX, size=k), strict=True)
    ]
    emails = [f"{f}.{la}.{a[-7:]}@{c}.example.com" for f, la, a, c in zip(first, last, anon_ids, co, strict=True)]
    return pd.DataFrame(
        {
            "anonymous_id": anon_ids,
            "email": emails,
            "first_name": [f.title() for f in first],
            "last_name": [la.title() for la in last],
            "company": [c.replace("-", " ").title() for c in co],
            "job_title": rng.choice(TITLES, size=k),
        }
    )


def build_form_fills(rng: np.random.Generator, sessions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = sessions["channel"].map(FILL_RATE).to_numpy()
    converting = sessions[rng.random(len(sessions)) < p]
    # One fill per visitor: their first converting session.
    converting = converting.drop_duplicates("anonymous_id", keep="first").reset_index(drop=True)
    people = _person_identity(rng, converting["anonymous_id"].to_numpy())
    submitted_utc = converting["session_start"] + pd.to_timedelta(
        rng.integers(60, 1500, size=len(converting)), unit="s"
    )
    # D3: written as naive America/New_York wall-clock time.
    submitted_local = (
        pd.DatetimeIndex(submitted_utc)
        .tz_localize("UTC")
        .tz_convert(LOCAL_TZ)
        .tz_localize(None)
        .astype("datetime64[us]")
    )
    fills = pd.DataFrame(
        {
            "form_fill_id": [f"ff_{i:06d}" for i in range(len(converting))],
            "session_id": converting["session_id"].to_numpy(),
            "anonymous_id": converting["anonymous_id"].to_numpy(),
            "email": people["email"].to_numpy(),
            "form_name": converting["landing_page"].map(FORM_FOR_PAGE).to_numpy(),
            "submitted_at": submitted_local,
        }
    )
    people["converting_channel"] = converting["channel"].to_numpy()
    people["submitted_utc"] = submitted_utc.to_numpy()
    people["form_fill_id"] = fills["form_fill_id"].to_numpy()
    return fills, people


def _email_variant(rng: np.random.Generator, email: str) -> str:
    s = int(rng.integers(0, 3))
    if s == 0:
        return email.upper()
    if s == 1:
        return f"  {email}"
    local, domain = email.split("@")
    return f"{local.title()}@{domain} "


def build_crm(
    rng: np.random.Generator, people: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    end_ts = pd.Timestamp(END_DATE) + pd.Timedelta(days=1)
    n = len(people)
    lead_created = people["submitted_utc"] + pd.to_timedelta(rng.integers(30, 600, size=n), unit="s")
    leads = pd.DataFrame(
        {
            "email": people["email"].to_numpy(),
            "created_at": lead_created.to_numpy(),
            "form_fill_id": people["form_fill_id"].to_numpy(),
            "lead_source": "web_form",
            "status": "new",
        }
    )
    # D2: duplicate leads with an email that differs by case / whitespace.
    dup_mask = rng.random(n) < DUPLICATE_LEAD_RATE
    dup_idx = np.flatnonzero(dup_mask)
    dups = pd.DataFrame(
        {
            "email": [_email_variant(rng, people["email"].iat[i]) for i in dup_idx],
            "created_at": (
                lead_created.iloc[dup_idx] + pd.to_timedelta(rng.integers(1, 30, size=len(dup_idx)), unit="D")
            ).to_numpy(),
            "form_fill_id": None,
            "lead_source": rng.choice(np.array(["list_import", "sales_manual"]), size=len(dup_idx)),
            "status": "new",
        }
    )
    dups = dups[dups["created_at"] < end_ts]
    leads = pd.concat([leads, dups], ignore_index=True)
    leads = leads.sort_values(["created_at", "email"], kind="stable").reset_index(drop=True)
    leads["lead_id"] = [f"00Q{i:07d}" for i in range(len(leads))]

    contacts = pd.DataFrame(
        {
            "contact_id": [f"003{i:07d}" for i in range(n)],
            "email": people["email"].to_numpy(),
            "first_name": people["first_name"].to_numpy(),
            "last_name": people["last_name"].to_numpy(),
            "company": people["company"].to_numpy(),
            "job_title": people["job_title"].to_numpy(),
            "created_at": lead_created.to_numpy(),
        }
    )

    # Opportunities + stage history.
    opp_p = people["converting_channel"].map(OPP_RATE).to_numpy()
    opp_mask = rng.random(n) < opp_p
    opp_rows: list[dict[str, object]] = []
    hist_rows: list[dict[str, object]] = []
    for i in np.flatnonzero(opp_mask):
        created = lead_created.iat[i] + pd.Timedelta(days=int(rng.integers(3, 45)), seconds=int(rng.integers(0, 86400)))
        if created >= end_ts:
            continue
        opp_id = f"006{len(opp_rows):07d}"
        amount = float(np.round(rng.lognormal(np.log(24000), 0.55), -2))
        t = created
        stage = STAGES[0]
        hist_rows.append({"opportunity_id": opp_id, "stage": stage, "entered_at": t})
        closed_at = None
        is_won = False
        for nxt in [*STAGES[1:], "closed"]:
            t = t + pd.Timedelta(days=int(rng.integers(5, 30)), seconds=int(rng.integers(0, 86400)))
            if t >= end_ts:
                break  # still open at end of data
            if nxt == "closed":
                is_won = bool(rng.random() < 0.55)
                stage = "closed_won" if is_won else "closed_lost"
                closed_at = t
            elif rng.random() < 0.22:  # lost before reaching next stage
                stage = "closed_lost"
                closed_at = t
            else:
                stage = nxt
            hist_rows.append({"opportunity_id": opp_id, "stage": stage, "entered_at": t})
            if closed_at is not None:
                break
        opp_rows.append(
            {
                "opportunity_id": opp_id,
                "contact_id": contacts["contact_id"].iat[i],
                "opportunity_name": f"{people['company'].iat[i]} - New Business",
                "created_at": created,
                "stage": stage,
                "amount_usd": amount,
                "close_date": closed_at.date() if closed_at is not None else None,
                "is_closed": closed_at is not None,
                "is_won": is_won,
            }
        )
    opps = pd.DataFrame(opp_rows)
    hist = pd.DataFrame(hist_rows)
    hist["stage_history_id"] = [f"osh_{i:07d}" for i in range(len(hist))]
    for df, col in ((leads, "created_at"), (contacts, "created_at"), (opps, "created_at"), (hist, "entered_at")):
        df[col] = pd.to_datetime(df[col]).astype("datetime64[us]")
    leads = leads[["lead_id", "email", "created_at", "form_fill_id", "lead_source", "status"]]
    hist = hist[["stage_history_id", "opportunity_id", "stage", "entered_at"]]
    return contacts, leads, opps, hist


def generate(seed: int = DEFAULT_SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.Generator(np.random.PCG64(seed))
    campaigns = build_campaigns()
    spend = build_ad_spend(rng)
    sessions = build_sessions(rng, spend)
    fills, people = build_form_fills(rng, sessions)
    contacts, leads, opps, hist = build_crm(rng, people)
    sessions = sessions[
        [
            "session_id",
            "anonymous_id",
            "session_start",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "referrer_domain",
            "landing_page",
            "pageviews",
        ]
    ]
    return {
        "campaigns": campaigns,
        "ad_spend": spend,
        "web_sessions": sessions,
        "form_fills": fills,
        "crm_contacts": contacts,
        "crm_leads": leads,
        "crm_opportunities": opps,
        "crm_opportunity_stage_history": hist,
    }


def write_parquet(tables: dict[str, pd.DataFrame], out: Path) -> dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name in TABLES:
        table = pa.Table.from_pandas(tables[name], preserve_index=False)
        table = table.replace_schema_metadata(None)  # drop pandas metadata for stable bytes
        path = out / f"{name}.parquet"
        pq.write_table(table, path, compression="zstd")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=Path("data/raw"))
    args = ap.parse_args(argv)
    tables = generate(args.seed)
    hashes = write_parquet(tables, args.out)
    for name in TABLES:
        print(f"{name:32s} {len(tables[name]):>8d} rows  sha256={hashes[name][:12]}")


if __name__ == "__main__":
    main()
