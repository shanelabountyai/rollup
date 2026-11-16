-- Q: How many opportunities and how much pipeline sit in each stage?
select stage, count(opportunity_id) as opportunities, sum(amount_usd) as amount_usd
from marts.fct_pipeline
group by stage
order by amount_usd desc
