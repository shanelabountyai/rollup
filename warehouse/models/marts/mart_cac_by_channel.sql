-- Monthly CAC by channel: paid spend / new customers credited to the channel by FIRST touch.
with months as (
    select range::date as month_start
    from range(
        (select min(spend_month) from {{ ref('fct_spend') }}),
        (select max(spend_month) + interval 1 month from {{ ref('fct_spend') }}),
        interval 1 month
    )
),

grid as (
    select m.month_start, c.channel_key, c.is_paid from months m cross join {{ ref('dim_channel') }} c
),

spend as (
    select spend_month as month_start, channel_key, sum(spend_usd) as spend_usd
    from {{ ref('fct_spend') }}
    group by 1, 2
),

customers as (
    select date_trunc('month', close_date)::date as month_start,
           coalesce(first_touch_channel_key, 'direct') as channel_key,
           count(*) as new_customers,
           sum(won_amount_usd) as new_customer_revenue_usd
    from {{ ref('fct_pipeline') }}
    where is_won
    group by 1, 2
)

select
    g.month_start,
    g.channel_key,
    g.is_paid,
    coalesce(s.spend_usd, 0)                            as spend_usd,
    coalesce(c.new_customers, 0)                        as new_customers,
    coalesce(c.new_customer_revenue_usd, 0)             as new_customer_revenue_usd,
    case when g.is_paid and coalesce(c.new_customers, 0) > 0
         then round(coalesce(s.spend_usd, 0) / c.new_customers, 2) end as cac_usd
from grid g
left join spend s using (month_start, channel_key)
left join customers c using (month_start, channel_key)
