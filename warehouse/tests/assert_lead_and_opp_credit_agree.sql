-- The funnel's *_last_touch columns credit leads via the converting session and opps/wins via
-- last_touch_channel_key; both must name the same channel for every person.
select p.opportunity_id, s.channel_key as lead_channel, p.last_touch_channel_key
from {{ ref('fct_pipeline') }} p
join {{ ref('int_leads_stitched') }} l using (person_key)
join {{ ref('int_sessions_classified') }} s on s.session_id = l.converting_session_id
where s.channel_key is distinct from p.last_touch_channel_key
