-- D-20: the funnel and CAC marts use the same attribution model, so per channel, funnel wins
-- equal CAC customers (count and revenue) under first touch (primary columns) and under last touch.
with funnel as (
    select channel_key,
           sum(deals_won)                  as wins_ft,
           sum(won_revenue_usd)            as rev_ft,
           sum(deals_won_last_touch)       as wins_lt,
           sum(won_revenue_usd_last_touch) as rev_lt
    from {{ ref('mart_funnel_weekly') }}
    group by 1
),

cac as (
    select channel_key,
           sum(new_customers)                       as wins_ft,
           sum(new_customer_revenue_usd)            as rev_ft,
           sum(new_customers_last_touch)            as wins_lt,
           sum(new_customer_revenue_usd_last_touch) as rev_lt
    from {{ ref('mart_cac_by_channel') }}
    group by 1
)

select channel_key,
       f.wins_ft as funnel_wins_first_touch, c.wins_ft as cac_customers_first_touch,
       f.wins_lt as funnel_wins_last_touch,  c.wins_lt as cac_customers_last_touch
from funnel f
full outer join cac c using (channel_key)
where coalesce(f.wins_ft, 0) <> coalesce(c.wins_ft, 0)
   or coalesce(f.wins_lt, 0) <> coalesce(c.wins_lt, 0)
   or abs(coalesce(f.rev_ft, 0) - coalesce(c.rev_ft, 0)) > 0.01
   or abs(coalesce(f.rev_lt, 0) - coalesce(c.rev_lt, 0)) > 0.01
