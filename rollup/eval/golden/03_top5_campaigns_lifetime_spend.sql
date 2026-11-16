-- Q: Which five campaigns have the highest lifetime spend?
-- ordered: true
select campaign_name, lifetime_spend_usd
from marts.dim_campaign
order by lifetime_spend_usd desc
limit 5
