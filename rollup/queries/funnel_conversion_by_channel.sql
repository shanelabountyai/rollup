-- Q: What are lead-to-opportunity and opportunity-to-win rates by first-touch channel?
select
    channel_key,
    sum(new_leads) as leads,
    sum(opportunities_created) as opportunities,
    sum(deals_won) as wins,
    round(100.0 * sum(opportunities_created) / nullif(sum(new_leads), 0), 1) as lead_to_opp_pct,
    round(100.0 * sum(deals_won) / nullif(sum(opportunities_created), 0), 1) as opp_to_win_pct
from marts.mart_funnel_weekly
group by channel_key
order by leads desc, channel_key
