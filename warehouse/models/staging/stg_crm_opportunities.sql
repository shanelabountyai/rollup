select
    opportunity_id,
    contact_id,
    opportunity_name,
    cast(created_at as timestamp)                as created_at,
    stage,
    cast(amount_usd as decimal(14, 2))           as amount_usd,
    cast(close_date as date)                     as close_date,
    cast(is_closed as boolean)                   as is_closed,
    cast(is_won as boolean)                      as is_won
from {{ source('raw', 'crm_opportunities') }}
