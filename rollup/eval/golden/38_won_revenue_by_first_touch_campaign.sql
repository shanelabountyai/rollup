-- Q: Which five campaigns sourced the most won revenue as first touch?
-- ordered: true
select c.campaign_name, sum(p.won_amount_usd) as won_revenue_usd
from marts.fct_pipeline as p
join marts.dim_campaign as c on c.campaign_id = p.first_touch_campaign_id
group by c.campaign_name
order by won_revenue_usd desc, c.campaign_name
limit 5
