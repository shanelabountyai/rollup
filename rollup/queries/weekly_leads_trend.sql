-- Q: How many new leads did we get each week across all channels?
select week_start, sum(new_leads) as new_leads, sum(form_fills) as form_fills, sum(sessions) as sessions
from marts.mart_funnel_weekly
group by week_start
order by week_start
