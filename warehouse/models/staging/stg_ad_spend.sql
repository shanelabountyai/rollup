select
    campaign_id || '|' || strftime(cast(report_date as date), '%Y-%m-%d') as spend_id,
    platform,
    campaign_id,
    trim(campaign_name)                          as campaign_name,
    {{ slugify('campaign_name') }}               as utm_campaign_key,
    cast(report_date as date)                    as spend_date,
    cast(spend_usd as decimal(12, 2))            as spend_usd,
    cast(impressions as bigint)                  as impressions,
    cast(clicks as bigint)                       as clicks
from {{ source('raw', 'ad_spend') }}
