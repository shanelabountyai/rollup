-- Sessions by a known person up to (and including) their converting form fill.
with lead_people as (
    select person_key, anonymous_id, first_lead_created_at
    from {{ ref('int_leads_stitched') }}
    where anonymous_id is not null
),

ordered as (
    select
        p.person_key,
        s.*,
        row_number() over (partition by p.person_key order by s.session_start_at, s.session_id) as touch_number,
        count(*) over (partition by p.person_key)                                               as touch_count
    from lead_people p
    join {{ ref('int_sessions_classified') }} s
        on s.anonymous_id = p.anonymous_id
       and s.session_start_at <= p.first_lead_created_at
)

select * from ordered
