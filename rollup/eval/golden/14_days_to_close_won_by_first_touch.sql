-- Q: On average, how many days do won deals take to close, by first-touch channel?
-- ordered: false
select first_touch_channel_key, avg(days_to_close) as avg_days_to_close
from marts.fct_pipeline
where is_won
group by first_touch_channel_key
