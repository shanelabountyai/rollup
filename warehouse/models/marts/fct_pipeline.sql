with first_last as (
    select
        person_key,
        max(case when is_first_touch then channel_key end)  as first_touch_channel_key,
        max(case when is_first_touch then campaign_id end)  as first_touch_campaign_id,
        max(case when is_last_touch then channel_key end)   as last_touch_channel_key,
        max(case when is_last_touch then campaign_id end)   as last_touch_campaign_id
    from {{ ref('fct_touches') }}
    group by 1
)

select
    o.opportunity_id,
    o.contact_id,
    l.person_key,
    o.opportunity_name,
    o.created_at,
    {{ local_date('o.created_at') }}                        as created_date,  -- local business day
    o.stage,
    o.amount_usd,
    o.is_closed,
    o.is_won,
    o.close_date,
    case when o.is_won then o.amount_usd else 0 end         as won_amount_usd,
    case when o.is_closed then date_diff('day', {{ local_date('o.created_at') }}, o.close_date) end as days_to_close,
    l.first_lead_created_at,
    fl.first_touch_channel_key,
    fl.first_touch_campaign_id,
    fl.last_touch_channel_key,
    fl.last_touch_campaign_id
from {{ ref('stg_crm_opportunities') }} o
join {{ ref('int_leads_stitched') }} l using (contact_id)
left join first_last fl using (person_key)
