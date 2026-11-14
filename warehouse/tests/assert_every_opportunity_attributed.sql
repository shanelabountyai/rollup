-- Every opportunity traces back to a stitched person with a first-touch channel.
select o.opportunity_id
from {{ ref('stg_crm_opportunities') }} o
left join {{ ref('fct_pipeline') }} p using (opportunity_id)
where p.opportunity_id is null or p.first_touch_channel_key is null
