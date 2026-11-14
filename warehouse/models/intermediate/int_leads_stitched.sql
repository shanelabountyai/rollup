-- D2: one row per person. Duplicate leads (email differing by case/whitespace) collapse
-- onto the earliest lead for the normalised email.
with ranked as (
    select
        *,
        row_number() over (partition by person_key order by created_at, lead_id) as rn,
        count(*) over (partition by person_key)                                  as lead_count
    from {{ ref('stg_crm_leads') }}
),

first_fill as (
    select person_key, min(form_fill_id) as form_fill_id
    from {{ ref('stg_crm_leads') }}
    where form_fill_id is not null
    group by 1
)

select
    r.person_key,
    r.email,
    r.lead_id                                    as primary_lead_id,
    r.created_at                                 as first_lead_created_at,
    r.lead_source                                as first_lead_source,
    r.lead_count,
    r.lead_count - 1                             as duplicate_lead_count,
    c.contact_id,
    f.form_fill_id,
    ff.anonymous_id,
    ff.session_id                                as converting_session_id
from ranked r
left join first_fill f using (person_key)
left join {{ ref('stg_form_fills') }} ff on ff.form_fill_id = f.form_fill_id
left join {{ ref('stg_crm_contacts') }} c using (person_key)
where r.rn = 1
