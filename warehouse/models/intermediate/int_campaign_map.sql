-- D4: every name a campaign has ever carried -> its stable campaign_id.
-- Built from daily spend (historical names) plus the catalogue snapshot (current names).
with names as (
    {% if var('unfix', '') == 'D4' -%}
    select campaign_id, platform, campaign_name, utm_campaign_key, start_date as seen_date
    from {{ ref('stg_campaigns') }}
    {%- else -%}
    select campaign_id, platform, campaign_name, utm_campaign_key, spend_date as seen_date
    from {{ ref('stg_ad_spend') }}
    {%- endif %}
    union all
    select campaign_id, platform, campaign_name, utm_campaign_key, cast(null as date) as seen_date
    from {{ ref('stg_campaigns') }}
),

agg as (
    select
        utm_campaign_key,
        campaign_id,
        platform,
        any_value(campaign_name)                 as campaign_name,
        min(seen_date)                           as first_seen_date,
        max(seen_date)                           as last_seen_date
    from names
    group by 1, 2, 3
)

select
    agg.*,
    agg.utm_campaign_key = c.utm_campaign_key    as is_current_name
from agg
join {{ ref('stg_campaigns') }} c using (campaign_id)
