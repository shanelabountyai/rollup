-- Q: How much did each paid channel spend in Q1 2026?
-- ordered: false
select channel_key, sum(spend_usd) as spend_usd
from marts.fct_spend
where spend_date >= date '2026-01-01' and spend_date < date '2026-04-01'
group by channel_key
