-- Q: What is the closed win rate and average deal size by first-touch channel?
select
    coalesce(p.first_touch_channel_key, 'direct') as channel_key,
    c.channel_group,
    count(p.opportunity_id) filter (where p.is_closed) as closed_opportunities,
    count(p.opportunity_id) filter (where p.is_won) as won_opportunities,
    round(100.0 * count(p.opportunity_id) filter (where p.is_won)
        / nullif(count(p.opportunity_id) filter (where p.is_closed), 0), 1) as win_rate_pct,
    round(avg(p.amount_usd) filter (where p.is_won), 2) as avg_won_deal_usd
from marts.fct_pipeline as p
join marts.dim_channel as c on c.channel_key = coalesce(p.first_touch_channel_key, 'direct')
group by 1, 2
order by won_opportunities desc, channel_key
