-- Q: How much did we spend on each paid channel per month?
select spend_month, channel_key, sum(spend_usd) as spend_usd, sum(clicks) as clicks
from marts.fct_spend
group by spend_month, channel_key
order by spend_month, channel_key
