-- Q: How many web sessions did each channel drive?
-- ordered: false
select channel_key, sum(sessions) as sessions
from marts.mart_funnel_weekly
group by channel_key
