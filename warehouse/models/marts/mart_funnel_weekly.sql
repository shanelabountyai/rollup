-- Weekly funnel by channel, bucketed on local business days (same calendar as spend).
-- Leads/opps/wins use last-touch (converting) channel.
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

leads as (
    select date_trunc('week', {{ local_date('l.first_lead_created_at') }})::date as week_start,
           coalesce(s.channel_key, 'direct') as channel_key,
           count(*) as new_leads
    from {{ ref('int_leads_stitched') }} l
    left join {{ ref('int_sessions_classified') }} s on s.session_id = l.converting_session_id
    group by 1, 2
),

opps as (
    select date_trunc('week', created_date)::date as week_start,
           coalesce(last_touch_channel_key, 'direct') as channel_key,
           count(*) as opportunities_created,
           sum(amount_usd) as pipeline_created_usd
    from {{ ref('fct_pipeline') }}
    group by 1, 2
),

wins as (
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
    coalesce(sp.spend_usd, 0)                       as spend_usd
from grid g
left join sessions s using (week_start, channel_key)
left join fills f    using (week_start, channel_key)
left join leads l    using (week_start, channel_key)
left join opps o     using (week_start, channel_key)
left join wins w     using (week_start, channel_key)
left join spend sp   using (week_start, channel_key)
