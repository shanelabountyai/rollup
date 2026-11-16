-- Q: How many deals did each channel win under first-touch versus last-touch credit?
-- ordered: false
select channel_key, sum(deals_won) as deals_won_first_touch, sum(deals_won_last_touch) as deals_won_last_touch
from marts.mart_funnel_weekly
group by channel_key
