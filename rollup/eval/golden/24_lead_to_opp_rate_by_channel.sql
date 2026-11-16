-- Q: What share of new leads became opportunities, by first-touch channel?
-- ordered: false
select channel_key, sum(opportunities_created)::double / nullif(sum(new_leads), 0) as lead_to_opp_rate
from marts.mart_funnel_weekly
group by channel_key
