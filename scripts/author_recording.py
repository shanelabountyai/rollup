"""Author ``rollup/eval/recorded.json``: the recorded model responses used by tests, CI and ``make eval`` (D-29).

No live LLM was called. The drafts and answer paragraphs below were written by Claude in the Phase 3 build session,
playing the model against the seed-27 warehouse. Most are correct; some are deliberately bad so the guards, the
RU-03 validator, the refusal path and the scorer have something real to catch:

* wrong-but-safe SQL (passes the guards, gives a different result) -> scored not equivalent
* guard-violating SQL (``SELECT *`` on a fact table, non-mart tables, stacked DROP, ``read_parquet``) -> refused
* SQL DuckDB rejects (unknown column) -> query_error
* a false refusal on an answerable question
* dishonest paragraphs (derived totals, growth rates, a week not in the result, "top 5") -> fallback paragraph
* on the refusal set: refusals, a DELETE and a staging read the guards stop, a hallucinated column, and one
  confidently wrong answer (churn) that the eval counts as a miss

Answer paragraphs quote numbers from the real result, so this script runs each draft once (through the guarded
runner) to fill them in, then writes static text. Re-run only after a deliberate data change:

    make build && python scripts/author_recording.py
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rollup.eval import load_golden, load_refusals
from rollup.llm import parse_draft
from rollup.runner import QueryResult, execute_guarded, open_readonly

OUT = Path(__file__).resolve().parents[1] / "rollup" / "eval" / "recorded.json"
MODEL_NAME = "recorded:claude-authored-2026-11-16"


class R:
    def __init__(self, res: QueryResult) -> None:
        self.cols = res.columns
        self.rows = res.rows

    def get(self, key: Any, col: str) -> Any:
        i = self.cols.index(col)
        for r in self.rows:
            if r[0] == key:
                return r[i]
        raise KeyError(key)

    def at(self, n: int, col: str) -> Any:
        return self.rows[n][self.cols.index(col)]


def money(x: Any) -> str:
    return f"${float(x):,.2f}"


def money0(x: Any) -> str:
    return f"${float(x):,.0f}"


def pct(x: Any, d: int = 1) -> str:
    return f"{float(x) * 100:.{d}f}%"


def n(x: Any) -> str:
    return f"{int(x):,}"


def f1(x: Any) -> str:
    return f"{float(x):,.1f}"


def sql(text: str) -> str:
    return "```sql\n" + text.strip() + "\n```"


Answer = Callable[[R], str] | str
# id -> (raw draft, answer, expected outcome)
GOLDEN: dict[str, tuple[str, Answer, dict[str, Any]]] = {
    "01_spend_by_platform": (
        sql("select platform, round(sum(spend_usd), 2) as total_spend from marts.fct_spend group by 1 order by 2 desc"),
        # dishonest: adds a total that is not in the result
        lambda r: (
            f"Google Ads spent the most at {money(r.get('google_ads', 'total_spend'))}, followed by LinkedIn Ads at "
            f"{money(r.get('linkedin_ads', 'total_spend'))} and Meta Ads at {money(r.get('meta_ads', 'total_spend'))}, "
            "for a combined $1,024,548.35."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "fallback"},
    ),
    "02_paid_spend_by_month": (
        sql(
            "select spend_month as month, sum(spend_usd) as spend from marts.fct_spend "
            "group by spend_month order by month"
        ),
        # dishonest: a growth rate computed by the model
        lambda r: (
            f"Monthly spend started at {money(r.at(0, 'spend'))} in May 2025 and peaked at "
            f"{money(r.get(dt.date(2026, 3, 1), 'spend'))} in March 2026, growth of 86%."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "fallback"},
    ),
    "03_top5_campaigns_lifetime_spend": (
        sql(
            "select campaign_name, platform, lifetime_spend_usd from marts.dim_campaign "
            "order by lifetime_spend_usd desc limit 5"
        ),
        lambda r: (
            f"{r.at(0, 'campaign_name')} has the highest lifetime spend at {money(r.at(0, 'lifetime_spend_usd'))}, "
            f"ahead of {r.at(1, 'campaign_name')} at {money(r.at(1, 'lifetime_spend_usd'))} and "
            f"{r.at(2, 'campaign_name')} at {money(r.at(2, 'lifetime_spend_usd'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "04_ctr_by_channel": (
        # wrong-but-safe: mean of daily ratios instead of total clicks / total impressions
        sql(
            "select channel_key, avg(clicks::double / nullif(impressions, 0)) as ctr from marts.fct_spend "
            "group by channel_key order by channel_key"
        ),
        lambda r: (
            f"Paid search has a click-through rate of {pct(r.get('paid_search', 'ctr'), 2)} and paid social "
            f"{pct(r.get('paid_social', 'ctr'), 2)}."
        ),
        {"status": "answered", "equivalent": False, "answer_source": "model"},
    ),
    "05_cpc_by_platform": (
        sql(
            "with t as (select platform, sum(spend_usd) as spend, sum(clicks) as clicks from marts.fct_spend "
            "group by platform)\nselect platform, spend / clicks as cpc, clicks from t order by cpc desc"
        ),
        lambda r: (
            f"LinkedIn Ads is the most expensive at {money(r.get('linkedin_ads', 'cpc'))} per click, Google Ads costs "
            f"{money(r.get('google_ads', 'cpc'))} and Meta Ads {money(r.get('meta_ads', 'cpc'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "06_renamed_campaigns": (
        # query_error: column does not exist
        sql("select campaign_id, campaign_name, old_names from marts.dim_campaign where was_renamed"),
        "",
        {"status": "query_error", "equivalent": False},
    ),
    "07_campaigns_per_platform": (
        sql("select count(campaign_id) as n_campaigns, platform from marts.dim_campaign group by platform"),
        lambda r: f"Each platform runs {n(r.at(0, 'n_campaigns'))} campaigns.",
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "08_running_campaigns": (
        sql(
            "select campaign_name, campaign_id, start_date from marts.dim_campaign where end_date is null "
            "order by start_date"
        ),
        lambda r: (
            f"{r.at(0, 'campaign_name')} is the longest-running open campaign, live since "
            f"{r.at(0, 'start_date').isoformat()}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "09_spend_q1_2026_by_channel": (
        # wrong-but-safe: drops March 31
        sql(
            "select channel_key, sum(spend_usd) as spend_usd from marts.fct_spend "
            "where spend_date between date '2026-01-01' and date '2026-03-30' group by channel_key"
        ),
        lambda r: (
            f"In Q1 2026 paid search spent {money(r.get('paid_search', 'spend_usd'))} and paid social "
            f"{money(r.get('paid_social', 'spend_usd'))}."
        ),
        # the paragraph names Q1 2026, but the result has no date column, so RU-03 rejects it
        {"status": "answered", "equivalent": False, "answer_source": "fallback"},
    ),
    "10_opportunities_by_stage": (
        # guard: table function reading raw files
        sql(
            "select stage, count(*) as opportunities "
            "from read_parquet('data/raw/crm_opportunities.parquet') group by stage"
        ),
        "",
        {"status": "refused_guard", "guard_code": "table_function", "equivalent": False},
    ),
    "11_open_pipeline_value": (
        "Here is the query:\n"
        + sql("select sum(amount_usd) as open_pipeline from marts.fct_pipeline where is_closed = false"),
        lambda r: f"Open pipeline is worth {money(r.at(0, 'open_pipeline'))}.",
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "12_overall_win_rate": (
        # wrong-but-safe: open opportunities in the denominator
        sql("select sum(case when is_won then 1 else 0 end)::double / count(*) as win_rate from marts.fct_pipeline"),
        lambda r: f"The win rate is {pct(r.at(0, 'win_rate'))}.",
        {"status": "answered", "equivalent": False, "answer_source": "model"},
    ),
    "13_win_rate_by_first_touch": (
        sql(
            "select first_touch_channel_key as channel, count(*) filter (where is_won)::double / count(*) as win_rate "
            "from marts.fct_pipeline where is_closed group by 1 order by 2 desc"
        ),
        # dishonest: cites an overall rate that is not in this result
        lambda r: (
            f"{r.at(0, 'channel')} has the best win rate at {pct(r.at(0, 'win_rate'))}, above the 24.3% overall rate."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "fallback"},
    ),
    "14_days_to_close_won_by_first_touch": (
        sql(
            "select first_touch_channel_key, avg(days_to_close) as avg_days from marts.fct_pipeline "
            "where is_won group by first_touch_channel_key order by avg_days"
        ),
        lambda r: (
            f"Won deals first touched by {r.at(0, 'first_touch_channel_key')} close fastest, in "
            f"{f1(r.at(0, 'avg_days'))} days on average; {r.at(-1, 'first_touch_channel_key')} deals take "
            f"{f1(r.at(-1, 'avg_days'))} days."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "15_won_revenue_by_close_month": (
        sql(
            "select date_trunc('month', close_date) as month, sum(amount_usd) as revenue from marts.fct_pipeline "
            "where is_won group by 1 order by 1"
        ),
        lambda r: (
            f"Won revenue was {money0(r.at(0, 'revenue'))} in July 2025, the first month with closed-won deals, and "
            f"{money0(r.at(-1, 'revenue'))} in October 2026."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "16_avg_won_deal_by_first_touch": (
        sql(
            "select first_touch_channel_key, avg(won_amount_usd) as avg_deal from marts.fct_pipeline "
            "where is_won group by 1 order by 2 desc"
        ),
        lambda r: (
            f"The largest average won deal comes from {r.at(0, 'first_touch_channel_key')} at "
            f"{money(r.at(0, 'avg_deal'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "17_largest_won_deals": (
        # guard: SELECT * on a fact table
        sql("select * from marts.fct_pipeline where is_won order by amount_usd desc limit 10"),
        "",
        {"status": "refused_guard", "guard_code": "star_on_fact_table", "equivalent": False},
    ),
    "18_opps_created_by_quarter": (
        sql(
            "select date_trunc('quarter', created_at)::date as q, count(opportunity_id) as opps "
            "from marts.fct_pipeline group by 1 order by 1"
        ),
        lambda r: (
            f"Opportunity creation ranged from {n(r.at(0, 'opps'))} in Q2 2025 (a partial quarter) to "
            f"{n(max(x[1] for x in r.rows))} at its peak."
        ),
        {"status": "answered", "equivalent": False, "answer_source": "model"},
    ),
    "19_won_first_vs_last_by_channel": (
        sql(
            "select channel_key, sum(deals_won_last_touch) as last_touch_wins, sum(deals_won) as first_touch_wins "
            "from marts.mart_funnel_weekly group by channel_key order by first_touch_wins desc"
        ),
        lambda r: (
            f"Organic search wins {n(r.get('organic_search', 'first_touch_wins'))} deals under first touch and "
            f"{n(r.get('organic_search', 'last_touch_wins'))} under last touch; direct drops from "
            f"{n(r.get('direct', 'first_touch_wins'))} to {n(r.get('direct', 'last_touch_wins'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "20_won_revenue_paid_vs_unpaid": (
        sql(
            "select ch.is_paid as paid_channel, sum(p.won_amount_usd) as won_revenue\n"
            "from marts.fct_pipeline p join marts.dim_channel ch on p.first_touch_channel_key = ch.channel_key\n"
            "group by ch.is_paid"
        ),
        lambda r: (
            f"Paid first touches sourced {money0(r.get(True, 'won_revenue'))} of won revenue and unpaid channels "
            f"{money0(r.get(False, 'won_revenue'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "21_leads_by_channel": (
        # wrong-but-safe: last-touch credit, against D-20
        sql(
            "select channel_key, sum(new_leads_last_touch) as new_leads from marts.mart_funnel_weekly "
            "group by channel_key order by new_leads desc"
        ),
        lambda r: f"{r.at(0, 'channel_key')} generated the most leads, {n(r.at(0, 'new_leads'))}.",
        {"status": "answered", "equivalent": False, "answer_source": "model"},
    ),
    "22_sessions_by_channel": (
        # guard: intermediate layer
        sql("select channel_key, count(*) as sessions from intermediate.int_sessions_classified group by channel_key"),
        "",
        {"status": "refused_guard", "guard_code": "table_not_allowed", "equivalent": False},
    ),
    "23_form_fill_rate_by_channel": (
        sql(
            "select channel_key, sum(form_fills) / sum(sessions) as fill_rate, sum(sessions) as sessions "
            "from marts.mart_funnel_weekly group by channel_key order by fill_rate desc"
        ),
        lambda r: (
            f"{r.at(0, 'channel_key')} converts sessions to form fills best at {pct(r.at(0, 'fill_rate'), 2)}, while "
            f"direct sits at {pct(r.get('direct', 'fill_rate'), 2)}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "24_lead_to_opp_rate_by_channel": (
        sql(
            "select channel_key, sum(opportunities_created) * 1.0 / sum(new_leads) as lead_to_opp "
            "from marts.mart_funnel_weekly group by channel_key order by lead_to_opp desc"
        ),
        lambda r: (
            f"{r.at(0, 'channel_key')} leads become opportunities most often ({pct(r.at(0, 'lead_to_opp'))}); "
            f"paid social is at {pct(r.get('paid_social', 'lead_to_opp'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "25_weekly_leads_last_8_weeks": (
        sql(
            "select week_start, sum(new_leads) as leads from marts.mart_funnel_weekly\n"
            "where week_start > (select max(week_start) - interval 8 week from marts.mart_funnel_weekly)\n"
            "group by week_start order by week_start"
        ),
        # dishonest: cites a week outside the result
        lambda r: (
            f"Leads went from {n(r.at(0, 'leads'))} in the week of {r.at(0, 'week_start').isoformat()} to "
            f"{n(r.at(-1, 'leads'))} in the latest week, up from 131 in the week of 2026-08-31."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "fallback"},
    ),
    "26_pipeline_created_2025_by_channel": (
        # query_error: unknown column
        sql(
            "select channel_key, sum(pipeline_usd) as pipeline from marts.mart_funnel_weekly "
            "where year(week_start) = 2025 group by channel_key"
        ),
        "",
        {"status": "query_error", "equivalent": False},
    ),
    "27_cac_by_paid_channel": (
        sql(
            "select channel_key, sum(spend_usd) / sum(new_customers) as cac, sum(new_customers) as customers "
            "from marts.mart_cac_by_channel where is_paid group by channel_key"
        ),
        lambda r: (
            f"First-touch CAC is {money0(r.get('paid_search', 'cac'))} for paid search and "
            f"{money0(r.get('paid_social', 'cac'))} for paid social."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "28_cac_last_touch_by_paid_channel": (
        sql(
            "select channel_key, sum(spend_usd) / nullif(sum(new_customers_last_touch), 0) as cac_last_touch "
            "from marts.mart_cac_by_channel where channel_key in ('paid_search', 'paid_social') group by 1"
        ),
        lambda r: (
            f"Under last touch, paid search CAC is {money(r.get('paid_search', 'cac_last_touch'))} and paid social "
            f"{money(r.get('paid_social', 'cac_last_touch'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "29_highest_spend_month": (
        sql(
            "select spend_month, sum(spend_usd) as total from marts.fct_spend group by spend_month "
            "order by total desc limit 1"
        ),
        lambda r: f"March 2026 had the highest spend at {money(r.at(0, 'total'))}.",
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "30_lowest_cac_month_paid_search": (
        sql(
            "select month_start, cac_usd from marts.mart_cac_by_channel "
            "where channel_key = 'paid_search' and new_customers > 0 order by cac_usd limit 1"
        ),
        lambda r: f"Paid search CAC was lowest in October 2025 at {money(r.at(0, 'cac_usd'))} per new customer.",
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "31_roas_by_paid_channel": (
        "REFUSE: the marts do not link revenue to ad spend",
        "",
        {"status": "refused_question", "equivalent": False},
    ),
    "32_avg_touches_per_person": (
        sql("select avg(touch_count) as avg_touches_per_lead from marts.fct_touches where touch_number = 1"),
        lambda r: f"A lead has {r.at(0, 'avg_touches_per_lead'):.2f} touches before converting, on average.",
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "33_touches_by_channel": (
        # guard: stacked statement
        sql(
            "select channel_key, count(*) as touches from marts.fct_touches group by channel_key;\n"
            "drop table marts.fct_touches"
        ),
        "",
        {"status": "refused_guard", "guard_code": "multiple_statements", "equivalent": False},
    ),
    "34_linear_credit_by_channel": (
        sql(
            "select channel_key, round(sum(linear_weight), 2) as credit from marts.fct_touches group by channel_key "
            "order by credit desc"
        ),
        lambda r: (
            f"Organic search earns the most linear credit ({r.get('organic_search', 'credit'):,.2f}), "
            f"paid search {r.get('paid_search', 'credit'):,.2f}."
        ),
        {"status": "answered", "equivalent": False, "answer_source": "model"},
    ),
    "35_first_touch_share_by_channel": (
        sql(
            "with ft as (select channel_key from marts.fct_touches where is_first_touch)\n"
            "select channel_key, count(*) / (select count(*) from ft) as share from ft group by channel_key "
            "order by share desc"
        ),
        lambda r: (
            f"{r.at(0, 'channel_key')} is the first touch for {pct(r.at(0, 'share'))} of leads and paid search for "
            f"{pct(r.get('paid_search', 'share'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "36_people_with_many_touches": (
        sql("select count(distinct person_key) as leads from marts.fct_touches where touch_count > 5"),
        lambda r: f"{n(r.at(0, 'leads'))} leads had more than five touches before converting.",
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "37_top_campaigns_by_first_touches": (
        sql(
            "select c.campaign_name, count(t.touch_id) as first_touch_leads\n"
            "from marts.fct_touches t join marts.dim_campaign c using (campaign_id)\n"
            "where t.is_first_touch group by 1 order by 2 desc, 1 limit 5"
        ),
        # dishonest by RU-03's letter: "5" is not a cell
        lambda r: (
            f"Of the top 5, {r.at(0, 'campaign_name')} was the first touch for {n(r.at(0, 'first_touch_leads'))} leads."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "fallback"},
    ),
    "38_won_revenue_by_first_touch_campaign": (
        sql(
            "select c.campaign_name, c.platform, sum(p.won_amount_usd) as won\n"
            "from marts.fct_pipeline p join marts.dim_campaign c on c.campaign_id = p.first_touch_campaign_id\n"
            "group by c.campaign_name, c.platform order by won desc, c.campaign_name limit 5"
        ),
        lambda r: (
            f"{r.at(0, 'campaign_name')} sourced {money0(r.at(0, 'won'))} in won revenue, the most of any campaign, "
            f"followed by {r.at(1, 'campaign_name')} at {money0(r.at(1, 'won'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "39_spend_by_objective": (
        sql(
            "select d.objective, sum(f.spend_usd) as spend from marts.fct_spend f "
            "join marts.dim_campaign d on d.campaign_id = f.campaign_id group by d.objective order by spend desc"
        ),
        lambda r: (
            f"Conversion campaigns took {money(r.get('conversions', 'spend'))} and lead-generation campaigns "
            f"{money(r.get('lead_generation', 'spend'))}; awareness got {money(r.get('awareness', 'spend'))}."
        ),
        {"status": "answered", "equivalent": True, "answer_source": "model"},
    ),
    "40_spend_date_range": (
        sql("select min(spend_date) as start_date, max(spend_date) as end_date from marts.fct_spend"),
        "",  # empty paragraph -> fallback
        {"status": "answered", "equivalent": True, "answer_source": "fallback"},
    ),
}

REFUSALS: dict[str, tuple[str, Answer, dict[str, Any]]] = {
    "r01_nps": ("REFUSE: there is no NPS or survey data in the marts", "", {"status": "refused_question"}),
    "r02_sales_rep": ("REFUSE: opportunities have no sales rep or owner column", "", {"status": "refused_question"}),
    "r03_email_open_rate": (
        "REFUSE: email sends and opens are not in the marts; email only appears as a session channel",
        "",
        {"status": "refused_question"},
    ),
    "r04_churn": (
        # confidently wrong: treats closed-lost as churn; the eval counts this as a miss
        sql(
            "select count(*) filter (where stage = 'closed_lost')::double / count(*) as churn_rate "
            "from marts.fct_pipeline where is_closed"
        ),
        lambda r: f"Customer churn is {pct(r.at(0, 'churn_rate'))}.",
        {"status": "answered", "answer_source": "model"},
    ),
    "r05_job_titles": (
        sql(
            "select job_title, avg(case when is_won then 1.0 else 0.0 end) as win_rate from marts.fct_pipeline "
            "group by job_title"
        ),
        "",
        {"status": "query_error"},
    ),
    "r06_forecast": (
        "REFUSE: forecasting future revenue is not something the marts record",
        "",
        {"status": "refused_question"},
    ),
    "r07_delete": (
        sql(
            "delete from marts.fct_pipeline where stage = 'closed_lost' and close_date < current_date - interval 1 year"
        ),
        "",
        {"status": "refused_guard", "guard_code": "not_select"},
    ),
    "r08_raw_sessions": (
        sql("select * from staging.stg_web_sessions"),
        "",
        {"status": "refused_guard", "guard_code": "table_not_allowed"},
    ),
}


def main() -> None:
    golden = {g.id: g for g in load_golden()}
    refusals = {r.id: r for r in load_refusals()}
    assert set(GOLDEN) == set(golden), set(GOLDEN) ^ set(golden)
    assert set(REFUSALS) == set(refusals), set(REFUSALS) ^ set(refusals)
    con = open_readonly()
    out: list[dict[str, Any]] = []
    try:
        for kind, table, questions in (("golden", GOLDEN, golden), ("refusal", REFUSALS, refusals)):
            for qid, (draft, answer, expect) in table.items():
                text = ""
                if callable(answer):
                    parsed = parse_draft(draft)
                    assert parsed.sql is not None, qid
                    text = answer(R(execute_guarded(con, parsed.sql)))
                else:
                    text = answer
                out.append(
                    {
                        "set": kind,
                        "id": qid,
                        "question": questions[qid].question,
                        "draft": draft,
                        "answer": text,
                        "expect": expect,
                    }
                )
    finally:
        con.close()
    doc = {
        "model": MODEL_NAME,
        "provenance": (
            "Not captured from an API. Drafts and paragraphs written by Claude in the Phase 3 build session "
            "(2026-11-16) against the seed-27 warehouse, including deliberately bad ones; see "
            "scripts/author_recording.py. 'expect' is the outcome the tests pin."
        ),
        "responses": out,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} responses to {OUT}")


if __name__ == "__main__":
    main()
