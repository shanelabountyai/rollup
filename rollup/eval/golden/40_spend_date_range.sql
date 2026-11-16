-- Q: What date range does the ad spend data cover?
-- ordered: false
select min(spend_date) as first_spend_date, max(spend_date) as last_spend_date
from marts.fct_spend
