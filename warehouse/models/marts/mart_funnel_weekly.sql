-- Weekly funnel by channel, bucketed on local business days (same calendar as spend).
-- D-20: leads/opps/wins are credited by FIRST touch (primary columns, same model as
-- mart_cac_by_channel); the *_last_touch columns credit the converting (last) touch.
-- People with no pre-conversion touch are credited to 'direct' under both models.
with weeks as (
    select range::date as week_start
    from range(
        (select date_trunc('week', min(session_date)) from {{ ref('int_sessions_classified') }}),
        (select max(session_date) + interval 1 day from {{ ref('int_sessions_classified') }}),
        interval 7 day
    )
),

grid as (
    select w.week_start, c.channel_key from weeks w cross join {{ ref('dim_channel') }} c
),

sessions as (
    select date_trunc('week', session_date)::date as week_start, channel_key, count(*) as sessions
    from {{ ref('int_sessions_classified') }}
    group by 1, 2
),

fills as (
    select date_trunc('week', f.submitted_date)::date as week_start, s.channel_key, count(*) as form_fills
    from {{ ref('stg_form_fills') }} f
    join {{ ref('int_sessions_classified') }} s using (session_id)
    group by 1, 2
),

first_touch as (
    select person_key, channel_key as first_touch_channel_key
    from {{ ref('fct_touches') }}
    where is_first_touch
),

lead_credit as (
    select date_trunc('week', {{ local_date('l.first_lead_created_at') }})::date as week_start,
           coalesce(ft.first_touch_channel_key, 'direct') as first_touch_channel_key,
           coalesce(s.channel_key, 'direct')               as last_touch_channel_key
    from {{ ref('int_leads_stitched') }} l
    left join first_touch ft using (person_key)
    left join {{ ref('int_sessions_classified') }} s on s.session_id = l.converting_session_id
),

leads as (
    select week_start, first_touch_channel_key as channel_key, count(*) as new_leads
    from lead_credit
    group by 1, 2
),

leads_lt as (
    select week_start, last_touch_channel_key as channel_key, count(*) as new_leads
    from lead_credit
    group by 1, 2
),

opps as (
    select date_trunc('week', created_date)::date as week_start,
           coalesce(first_touch_channel_key, 'direct') as channel_key,
           count(*) as opportunities_created,
           sum(amount_usd) as pipeline_created_usd
    from {{ ref('fct_pipeline') }}
    group by 1, 2
),

opps_lt as (
    select date_trunc('week', created_date)::date as week_start,
           coalesce(last_touch_channel_key, 'direct') as channel_key,
           count(*) as opportunities_created,
           sum(amount_usd) as pipeline_created_usd
    from {{ ref('fct_pipeline') }}
    group by 1, 2
),

wins as (
    select date_trunc('week', close_date)::date as week_start,
           coalesce(first_touch_channel_key, 'direct') as channel_key,
           count(*) as deals_won,
           sum(won_amount_usd) as won_revenue_usd
    from {{ ref('fct_pipeline') }}
    where is_won
    group by 1, 2
),

wins_lt as (
    select date_trunc('week', close_date)::date as week_start,
           coalesce(last_touch_channel_key, 'direct') as channel_key,
           count(*) as deals_won,
           sum(won_amount_usd) as won_revenue_usd
    from {{ ref('fct_pipeline') }}
    where is_won
    group by 1, 2
),

spend as (
    select spend_week as week_start, channel_key, sum(spend_usd) as spend_usd
    from {{ ref('fct_spend') }}
    group by 1, 2
)

select
    g.week_start,
    g.channel_key,
    coalesce(s.sessions, 0)                         as sessions,
    coalesce(f.form_fills, 0)                       as form_fills,
    coalesce(l.new_leads, 0)                        as new_leads,
    coalesce(o.opportunities_created, 0)            as opportunities_created,
    coalesce(o.pipeline_created_usd, 0)             as pipeline_created_usd,
    coalesce(w.deals_won, 0)                        as deals_won,
    coalesce(w.won_revenue_usd, 0)                  as won_revenue_usd,
    coalesce(sp.spend_usd, 0)                       as spend_usd,
    coalesce(llt.new_leads, 0)                      as new_leads_last_touch,
    coalesce(olt.opportunities_created, 0)          as opportunities_created_last_touch,
    coalesce(olt.pipeline_created_usd, 0)           as pipeline_created_usd_last_touch,
    coalesce(wlt.deals_won, 0)                      as deals_won_last_touch,
    coalesce(wlt.won_revenue_usd, 0)                as won_revenue_usd_last_touch
from grid g
left join sessions s using (week_start, channel_key)
left join fills f    using (week_start, channel_key)
left join leads l    using (week_start, channel_key)
left join opps o     using (week_start, channel_key)
left join wins w     using (week_start, channel_key)
left join spend sp   using (week_start, channel_key)
left join leads_lt llt using (week_start, channel_key)
left join opps_lt olt  using (week_start, channel_key)
left join wins_lt wlt  using (week_start, channel_key)
