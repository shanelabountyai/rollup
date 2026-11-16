-- Q: How much revenue was won each month (by close date), in date order?
-- ordered: true
select date_trunc('month', close_date) as close_month, sum(won_amount_usd) as won_revenue_usd
from marts.fct_pipeline
where is_won
group by close_month
order by close_month
