select
    s.spend_id,
    s.spend_date,
    date_trunc('week', s.spend_date)::date   as spend_week,
    date_trunc('month', s.spend_date)::date  as spend_month,
    s.campaign_id,
    c.channel_key,
    s.platform,
    s.spend_usd,
    s.impressions,
    s.clicks
from {{ ref('stg_ad_spend') }} s
join {{ ref('stg_campaigns') }} c using (campaign_id)
