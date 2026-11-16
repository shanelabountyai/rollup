-- Q: What is the average cost per click on each ad platform?
-- ordered: false
select platform, sum(spend_usd) / sum(clicks) as cost_per_click_usd
from marts.fct_spend
group by platform
