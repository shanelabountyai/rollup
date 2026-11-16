-- Q: What share of closed opportunities were won?
-- ordered: false
select avg(case when is_won then 1.0 else 0.0 end) as win_rate
from marts.fct_pipeline
where is_closed
