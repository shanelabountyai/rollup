-- Q: How many leads had more than five touches before converting?
-- ordered: false
select count(*) as people
from marts.fct_touches
where is_first_touch and touch_count > 5
