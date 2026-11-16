-- Q: How many opportunities were created each quarter, in date order?
-- ordered: true
select date_trunc('quarter', created_date) as quarter_start, count(*) as opportunities
from marts.fct_pipeline
group by quarter_start
order by quarter_start
