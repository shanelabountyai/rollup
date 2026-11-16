-- Q: How much was spent per campaign objective?
-- ordered: false
select c.objective, sum(s.spend_usd) as spend_usd
from marts.fct_spend as s
join marts.dim_campaign as c on c.campaign_id = s.campaign_id
group by c.objective
