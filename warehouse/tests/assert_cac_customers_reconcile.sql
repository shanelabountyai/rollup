-- mart_cac_by_channel credits every won deal exactly once (count and revenue).
with t as (
    select
        (select sum(new_customers) from {{ ref('mart_cac_by_channel') }})            as cac_customers,
        (select count(*) from {{ ref('fct_pipeline') }} where is_won)                 as wins,
        (select sum(new_customer_revenue_usd) from {{ ref('mart_cac_by_channel') }}) as cac_revenue,
        (select sum(won_amount_usd) from {{ ref('fct_pipeline') }})                   as won_revenue
)
select * from t where cac_customers <> wins or abs(cac_revenue - won_revenue) > 0.01
