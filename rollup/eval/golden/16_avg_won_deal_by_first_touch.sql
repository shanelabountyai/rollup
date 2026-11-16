-- Q: What is the average won deal size by first-touch channel?
-- ordered: false
select first_touch_channel_key, avg(amount_usd) as avg_won_deal_usd
from marts.fct_pipeline
where is_won
group by first_touch_channel_key
