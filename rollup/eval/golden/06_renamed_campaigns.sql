-- Q: Which campaigns have been renamed, and what were their previous names?
-- ordered: false
select campaign_id, campaign_name, previous_names
from marts.dim_campaign
where was_renamed
