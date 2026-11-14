-- Q: How long do won deals take to close, by first-touch channel?
select
    coalesce(first_touch_channel_key, 'direct') as channel_key,
    count(opportunity_id) as won_deals,
    round(avg(days_to_close), 1) as avg_days_to_close,
    median(days_to_close) as median_days_to_close
from marts.fct_pipeline
where is_won
group by 1
order by avg_days_to_close, channel_key
