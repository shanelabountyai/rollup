-- Q: What is the total value of open (not closed) pipeline?
-- ordered: false
select sum(amount_usd) as open_pipeline_usd
from marts.fct_pipeline
where not is_closed
