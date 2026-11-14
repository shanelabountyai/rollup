-- D1 + D4: every paid session maps to a campaign despite casing drift and the rename.
select session_id, utm_campaign
from {{ ref('int_sessions_classified') }}
where channel_key in ('paid_search', 'paid_social') and campaign_id is null
