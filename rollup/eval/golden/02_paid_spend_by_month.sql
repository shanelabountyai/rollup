-- Q: What was total paid spend each month, in date order?
-- ordered: true
select spend_month, sum(spend_usd) as spend_usd
from marts.fct_spend
group by spend_month
order by spend_month
