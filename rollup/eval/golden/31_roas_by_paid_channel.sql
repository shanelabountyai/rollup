-- Q: What is the return on ad spend (first-touch new-customer revenue divided by spend) for each paid channel?
-- ordered: false
select channel_key, sum(new_customer_revenue_usd) / nullif(sum(spend_usd), 0) as roas
from marts.mart_cac_by_channel
where is_paid
group by channel_key
