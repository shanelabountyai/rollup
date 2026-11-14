select
    contact_id,
    lower(trim(email))                           as email,
    {{ person_key('email') }}                    as person_key,
    first_name,
    last_name,
    company,
    job_title,
    cast(created_at as timestamp)                as created_at
from {{ source('raw', 'crm_contacts') }}
