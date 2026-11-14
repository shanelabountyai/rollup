select
    form_fill_id,
    session_id,
    anonymous_id,
    lower(trim(email))                           as email,
    {{ person_key('email') }}                    as person_key,
    form_name,
    cast(submitted_at as timestamp)              as submitted_at_local,
    {{ local_to_utc('cast(submitted_at as timestamp)') }} as submitted_at,
    cast(submitted_at as date)                   as submitted_date  -- local business day
from {{ source('raw', 'form_fills') }}
