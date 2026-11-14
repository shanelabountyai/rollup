-- Totals survive modelling: raw spend = fct_spend = funnel spend = CAC spend (to the cent).
with t as (
    select
        (select sum(spend_usd) from {{ source('raw', 'ad_spend') }})      as raw_usd,
        (select sum(spend_usd) from {{ ref('fct_spend') }})              as fct_usd,
        (select sum(spend_usd) from {{ ref('mart_funnel_weekly') }})     as funnel_usd,
        (select sum(spend_usd) from {{ ref('mart_cac_by_channel') }})    as cac_usd
)
select * from t
where abs(raw_usd - fct_usd) > 0.01 or abs(raw_usd - funnel_usd) > 0.01 or abs(raw_usd - cac_usd) > 0.01
