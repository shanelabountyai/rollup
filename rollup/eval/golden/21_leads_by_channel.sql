-- Q: How many new leads did each channel generate (first touch)?
-- ordered: false
select channel_key, sum(new_leads) as new_leads
from marts.mart_funnel_weekly
group by channel_key
