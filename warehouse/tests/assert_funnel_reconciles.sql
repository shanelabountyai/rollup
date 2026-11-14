-- Funnel counts reconcile to their sources: sessions, fills, stitched leads, opps, wins.
-- Lead/opp/win totals must hold under first touch (primary columns) and last touch (*_last_touch).
with t as (
    select
        (select sum(sessions) from {{ ref('mart_funnel_weekly') }})                          as f_sessions,
        (select count(*) from {{ ref('stg_web_sessions') }})                                 as s_sessions,
        (select sum(form_fills) from {{ ref('mart_funnel_weekly') }})                        as f_fills,
        (select count(*) from {{ ref('stg_form_fills') }})                                   as s_fills,
        (select sum(new_leads) from {{ ref('mart_funnel_weekly') }})                         as f_leads,
        (select sum(new_leads_last_touch) from {{ ref('mart_funnel_weekly') }})              as f_leads_lt,
        (select count(*) from {{ ref('int_leads_stitched') }})                               as s_leads,
        (select sum(opportunities_created) from {{ ref('mart_funnel_weekly') }})             as f_opps,
        (select sum(opportunities_created_last_touch) from {{ ref('mart_funnel_weekly') }})  as f_opps_lt,
        (select count(*) from {{ ref('fct_pipeline') }})                                     as s_opps,
        (select sum(deals_won) from {{ ref('mart_funnel_weekly') }})                         as f_wins,
        (select sum(deals_won_last_touch) from {{ ref('mart_funnel_weekly') }})              as f_wins_lt,
        (select count(*) from {{ ref('fct_pipeline') }} where is_won)                        as s_wins
)
select * from t
where f_sessions <> s_sessions or f_fills <> s_fills
   or f_leads <> s_leads or f_leads_lt <> s_leads
   or f_opps <> s_opps or f_opps_lt <> s_opps
   or f_wins <> s_wins or f_wins_lt <> s_wins
