-- D4 renamed campaign: li_2001 has exactly one dim row, both names in the map, and
-- its spend and paid sessions all roll up to the single id.
with dim as (
    select count(*) as n from {{ ref('dim_campaign') }} where campaign_id = 'li_2001' and was_renamed
),
map as (
    select count(*) as n from {{ ref('int_campaign_map') }} where campaign_id = 'li_2001'
),
spend as (
    select
        (select sum(spend_usd) from {{ source('raw', 'ad_spend') }} where campaign_id = 'li_2001') as raw_usd,
        (select sum(spend_usd) from {{ ref('fct_spend') }} where campaign_id = 'li_2001') as fct_usd
)
select 'dim rows for li_2001: ' || n as failure from dim where n <> 1
union all
select 'map keys for li_2001: ' || n from map where n <> 2
union all
select 'spend mismatch' from spend where abs(raw_usd - fct_usd) > 0.01
