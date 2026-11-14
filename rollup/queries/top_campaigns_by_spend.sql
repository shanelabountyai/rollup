-- Q: Which ten campaigns spent the most, and were any renamed?
select campaign_id, campaign_name, platform, channel_key, lifetime_spend_usd, was_renamed, previous_names
from marts.dim_campaign
order by lifetime_spend_usd desc, campaign_id
limit 10
