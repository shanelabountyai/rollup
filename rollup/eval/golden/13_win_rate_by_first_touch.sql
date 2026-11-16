-- Q: What is the win rate of closed opportunities by first-touch channel?
-- ordered: false
select first_touch_channel_key, avg(case when is_won then 1.0 else 0.0 end) as win_rate
from marts.fct_pipeline
where is_closed
group by first_touch_channel_key
