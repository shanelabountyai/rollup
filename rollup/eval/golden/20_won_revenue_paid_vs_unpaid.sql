-- Q: How much won revenue came from paid versus unpaid first-touch channels?
-- ordered: false
select c.is_paid, sum(p.won_amount_usd) as won_revenue_usd
from marts.fct_pipeline as p
join marts.dim_channel as c on c.channel_key = p.first_touch_channel_key
group by c.is_paid
