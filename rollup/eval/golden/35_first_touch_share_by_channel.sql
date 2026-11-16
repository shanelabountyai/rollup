-- Q: What share of leads had their first touch in each channel?
-- ordered: false
select channel_key, count(*)::double / sum(count(*)) over () as first_touch_share
from marts.fct_touches
where is_first_touch
group by channel_key
