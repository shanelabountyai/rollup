-- Reporting calendar (D-15): sessions are dated on the local business day (the calendar ad
-- platforms report spend in), not the UTC date. On seed 27, UTC dating moves ~8% of sessions
-- to a different day. Also: every paid session falls on a day its campaign had spend.
select session_id, 'session_date is not the local business day' as failure
from {{ ref('stg_web_sessions') }}
where session_date <> cast(timezone('{{ var("local_tz") }}', timezone('UTC', session_start_at)) as date)

union all

select s.session_id, 'paid session on a day without campaign spend'
from {{ ref('int_sessions_classified') }} s
left join {{ ref('fct_spend') }} f
    on f.campaign_id = s.campaign_id and f.spend_date = s.session_date
where s.campaign_id is not null and f.spend_id is null
