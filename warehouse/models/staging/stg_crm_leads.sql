select
    lead_id,
    email                                        as email_raw,
    lower(trim(email))                           as email,
    {{ person_key('email') }}                    as person_key,
    cast(created_at as timestamp)                as created_at,
    form_fill_id,
    lead_source,
    status
from {{ source('raw', 'crm_leads') }}
