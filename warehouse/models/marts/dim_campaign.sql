with spend as (
    select
        campaign_id,
        sum(spend_usd)    as lifetime_spend_usd,
        min(spend_date)   as first_spend_date,
        max(spend_date)   as last_spend_date
    from {{ ref('stg_ad_spend') }}
    group by 1
),

names as (
    select
        campaign_id,
        count(*)                                                       as name_count,
        string_agg(campaign_name, ' | ' order by first_seen_date)
            filter (where not is_current_name)                        as previous_names
    from {{ ref('int_campaign_map') }}
    group by 1
)

select
    c.campaign_id,
    c.campaign_name,
    c.utm_campaign_key,
    c.platform,
    c.channel_key,
    c.objective,
    c.start_date,
    c.end_date,
    c.daily_budget_usd,
    n.name_count > 1                 as was_renamed,
    n.previous_names,
    coalesce(s.lifetime_spend_usd, 0) as lifetime_spend_usd,
    s.first_spend_date,
    s.last_spend_date
from {{ ref('stg_campaigns') }} c
left join names n using (campaign_id)
left join spend s using (campaign_id)
