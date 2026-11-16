-- Q: What is the overall first-touch CAC for each paid channel?
-- ordered: false
select channel_key, sum(spend_usd) / nullif(sum(new_customers), 0) as cac_usd
from marts.mart_cac_by_channel
where is_paid
group by channel_key
