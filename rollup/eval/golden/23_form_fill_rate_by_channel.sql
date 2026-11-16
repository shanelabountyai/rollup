-- Q: What is the form-fill rate (form fills per session) by channel?
-- ordered: false
select channel_key, sum(form_fills)::double / nullif(sum(sessions), 0) as form_fill_rate
from marts.mart_funnel_weekly
group by channel_key
