-- Q: What was total ad spend by platform?
-- ordered: false
select platform, sum(spend_usd) as spend_usd
from marts.fct_spend
group by platform
