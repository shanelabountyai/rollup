-- Q: Which campaigns are still running (no end date)?
-- ordered: false
select campaign_id, campaign_name
from marts.dim_campaign
where end_date is null
