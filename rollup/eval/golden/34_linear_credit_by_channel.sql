-- Q: How much linear attribution credit does each channel earn?
-- ordered: false
select channel_key, sum(linear_weight) as linear_credit
from marts.fct_touches
group by channel_key
