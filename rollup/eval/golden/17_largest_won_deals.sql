-- Q: What are the ten largest won deals?
-- ordered: true
select opportunity_id, opportunity_name, amount_usd
from marts.fct_pipeline
where is_won
order by amount_usd desc, opportunity_id
limit 10
