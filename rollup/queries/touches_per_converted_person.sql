-- Q: How many marketing touches does a person have before becoming a lead?
with per_person as (
    select person_key, max(touch_count) as touches
    from marts.fct_touches
    group by person_key
)
select touches, count(person_key) as people
from per_person
group by touches
order by touches
