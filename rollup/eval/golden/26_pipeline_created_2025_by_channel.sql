-- Q: How much pipeline did each channel create in weeks starting in 2025?
-- ordered: false
select channel_key, sum(pipeline_created_usd) as pipeline_created_usd
from marts.mart_funnel_weekly
where week_start >= date '2025-01-01' and week_start < date '2026-01-01'
group by channel_key
