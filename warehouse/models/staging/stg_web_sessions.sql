select
    session_id,
    anonymous_id,
    cast(session_start as timestamp)             as session_start_at,
    cast(session_start as date)                  as session_date,
    {{ clean_str('utm_source') }}                as utm_source,
    {{ clean_str('utm_medium') }}                as utm_medium,
    {{ clean_str('utm_campaign') }}              as utm_campaign,
    {{ clean_str('referrer_domain') }}           as referrer_domain,
    landing_page,
    cast(pageviews as integer)                   as pageviews
from {{ source('raw', 'web_sessions') }}
