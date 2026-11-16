-- Q: How many marketing touches did each channel get?
-- ordered: false
select channel_key, count(*) as touches
from marts.fct_touches
group by channel_key
