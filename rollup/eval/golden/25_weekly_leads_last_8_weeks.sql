-- Q: How many new leads came in each of the last eight weeks, in date order?
-- ordered: true
select week_start, sum(new_leads) as new_leads
from marts.mart_funnel_weekly
where week_start >= (select max(week_start) from marts.mart_funnel_weekly) - interval 7 week
group by week_start
order by week_start
