select
    campaign_id,
    platform,
    trim(campaign_name)                          as campaign_name,
    {{ slugify('campaign_name') }}               as utm_campaign_key,
    case when platform = 'google_ads' then 'paid_search' else 'paid_social' end as channel_key,
    objective,
    cast(start_date as date)                     as start_date,
    cast(end_date as date)                       as end_date,
    cast(daily_budget_usd as decimal(12, 2))     as daily_budget_usd
from {{ source('raw', 'campaigns') }}
