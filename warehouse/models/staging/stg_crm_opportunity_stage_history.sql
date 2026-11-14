select
    stage_history_id,
    opportunity_id,
    stage,
    cast(entered_at as timestamp)                as entered_at,
    lead(cast(entered_at as timestamp)) over (
        partition by opportunity_id order by entered_at
    )                                            as exited_at
from {{ source('raw', 'crm_opportunity_stage_history') }}
