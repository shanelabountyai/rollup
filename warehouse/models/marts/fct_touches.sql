-- Pre-conversion touches for every person who became a lead, with first / last / linear credit.
select
    session_id                                 as touch_id,
    person_key,
    session_start_at                           as touched_at,
    session_date                               as touch_date,
    channel_key,
    campaign_id,
    touch_number,
    touch_count,
    touch_number = 1                           as is_first_touch,
    touch_number = touch_count                 as is_last_touch,
    cast(1.0 / touch_count as double)          as linear_weight
from {{ ref('int_person_touches') }}
