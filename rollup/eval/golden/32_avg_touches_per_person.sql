-- Q: On average, how many pre-conversion touches does a lead have?
-- ordered: false
select avg(touch_count) as avg_touches
from marts.fct_touches
where is_first_touch
