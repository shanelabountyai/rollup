-- Q: What is the click-through rate (clicks divided by impressions) for each paid channel?
-- ordered: false
select channel_key, sum(clicks)::double / sum(impressions) as ctr
from marts.fct_spend
group by channel_key
