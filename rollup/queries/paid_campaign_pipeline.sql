-- Q: Which paid campaigns sourced the most won revenue by first touch, against their spend?
with won as (
    select first_touch_campaign_id as campaign_id, count(opportunity_id) as won_deals, sum(won_amount_usd) as won_revenue_usd
    from marts.fct_pipeline
    where is_won and first_touch_campaign_id is not null
    group by first_touch_campaign_id
)
select
    d.campaign_id,
    d.campaign_name,
    d.platform,
    d.lifetime_spend_usd,
    coalesce(w.won_deals, 0) as won_deals,
    coalesce(w.won_revenue_usd, 0) as won_revenue_usd,
    round(coalesce(w.won_revenue_usd, 0) / nullif(d.lifetime_spend_usd, 0), 2) as revenue_to_spend
from marts.dim_campaign as d
left join won as w on w.campaign_id = d.campaign_id
order by won_revenue_usd desc, d.campaign_id
