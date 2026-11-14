-- Q: What was CAC by paid channel each quarter (first touch, D-20)?
select
    date_trunc('quarter', month_start) as quarter_start,
    channel_key,
    sum(spend_usd) as spend_usd,
    sum(new_customers) as new_customers,
    round(sum(spend_usd) / nullif(sum(new_customers), 0), 2) as cac_usd
from marts.mart_cac_by_channel
where is_paid
group by quarter_start, channel_key
order by quarter_start, channel_key
