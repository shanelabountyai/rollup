-- Q: How many opportunities are in each stage?
-- ordered: false
select stage, count(*) as opportunities
from marts.fct_pipeline
group by stage
