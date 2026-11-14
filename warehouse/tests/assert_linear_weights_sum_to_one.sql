-- Linear attribution credit sums to 1 per person; exactly one first and one last touch.
select person_key, sum(linear_weight) as w,
       count(*) filter (where is_first_touch) as firsts,
       count(*) filter (where is_last_touch) as lasts
from {{ ref('fct_touches') }}
group by 1
having abs(sum(linear_weight) - 1) > 1e-9 or firsts <> 1 or lasts <> 1
