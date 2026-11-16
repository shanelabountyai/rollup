-- Q: Which month had the highest total ad spend?
-- ordered: true
select spend_month, sum(spend_usd) as spend_usd
from marts.fct_spend
group by spend_month
order by spend_usd desc
limit 1
