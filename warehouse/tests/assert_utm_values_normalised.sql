-- D1 UTM casing drift: every UTM value in staging is trimmed + lower-case, and every
-- drifted raw value collapses onto a canonical value (no extra distinct campaigns).
with bad as (
    select session_id, 'not normalised' as reason
    from {{ ref('stg_web_sessions') }}
    where utm_source <> lower(trim(utm_source))
       or utm_medium <> lower(trim(utm_medium))
       or utm_campaign <> lower(trim(utm_campaign))
),
counts as (
    select
        (select count(distinct utm_campaign) from {{ ref('stg_web_sessions') }}) as stg_n,
        (select count(distinct lower(trim(utm_campaign))) from {{ source('raw', 'web_sessions') }}) as raw_n
)
select session_id, reason from bad
union all
select null, 'distinct campaign count drifted: ' || stg_n || ' vs ' || raw_n from counts where stg_n <> raw_n
