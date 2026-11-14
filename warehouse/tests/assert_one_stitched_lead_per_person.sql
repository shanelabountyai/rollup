-- D2 duplicate leads: stitched leads = distinct normalised emails, and every raw lead
-- (including case/whitespace duplicates) lands on exactly one stitched person.
with expected as (
    select count(distinct lower(trim(email))) as n from {{ source('raw', 'crm_leads') }}
),
actual as (
    select count(*) as n, sum(lead_count) as leads from {{ ref('int_leads_stitched') }}
),
raw_total as (
    select count(*) as n from {{ source('raw', 'crm_leads') }}
)
select 'person count ' || a.n || ' <> ' || e.n as failure
from actual a, expected e where a.n <> e.n
union all
select 'lead coverage ' || a.leads || ' <> ' || r.n
from actual a, raw_total r where a.leads <> r.n
