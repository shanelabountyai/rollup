-- Channel classification + campaign mapping for every session.
select
    s.session_id,
    s.anonymous_id,
    s.session_start_at,
    s.session_date,
    case
        when s.utm_medium = 'cpc' then 'paid_search'
        when s.utm_medium = 'paid_social' then 'paid_social'
        when s.utm_medium = 'email' then 'email'
        when s.referrer_domain in ('google.com', 'bing.com', 'duckduckgo.com') then 'organic_search'
        when s.referrer_domain is not null then 'referral'
        else 'direct'
    end                                          as channel_key,
    m.campaign_id,
    s.utm_source,
    s.utm_medium,
    s.utm_campaign,
    s.referrer_domain,
    s.landing_page,
    s.pageviews
from {{ ref('stg_web_sessions') }} s
left join {{ ref('int_campaign_map') }} m
    on s.utm_medium in ('cpc', 'paid_social')
   and s.utm_campaign = m.utm_campaign_key
