-- mart_cac_by_channel credits every won deal exactly once (count and revenue), under first touch
-- (new_customers) and under last touch (new_customers_last_touch).
with t as (
    select
        (select count(*) from {{ ref('fct_pipeline') }} where is_won)                            as wins,
        (select sum(won_amount_usd) from {{ ref('fct_pipeline') }})                              as won_revenue,
        (select sum(new_customers) from {{ ref('mart_cac_by_channel') }})                        as cac_customers,
        (select sum(new_customer_revenue_usd) from {{ ref('mart_cac_by_channel') }})             as cac_revenue,
        (select sum(new_customers_last_touch) from {{ ref('mart_cac_by_channel') }})             as cac_customers_lt,
        (select sum(new_customer_revenue_usd_last_touch) from {{ ref('mart_cac_by_channel') }})  as cac_revenue_lt
)
select * from t
where cac_customers <> wins or abs(cac_revenue - won_revenue) > 0.01
   or cac_customers_lt <> wins or abs(cac_revenue_lt - won_revenue) > 0.01
