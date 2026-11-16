-- Q: How many campaigns run on each platform?
-- ordered: false
select platform, count(*) as campaigns
from marts.dim_campaign
group by platform
