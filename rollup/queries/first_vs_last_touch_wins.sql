-- Q: How do won deals and revenue per channel differ between first-touch and last-touch credit?
select
    channel_key,
    sum(deals_won) as deals_won_first_touch,
    sum(deals_won_last_touch) as deals_won_last_touch,
    sum(won_revenue_usd) as won_revenue_first_touch_usd,
    sum(won_revenue_usd_last_touch) as won_revenue_last_touch_usd
from marts.mart_funnel_weekly
group by channel_key
order by deals_won_first_touch desc, channel_key
