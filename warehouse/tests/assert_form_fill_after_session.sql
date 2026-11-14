-- D3 timezone mismatch: once converted to UTC, every form fill happens after its session
-- started and within an hour. Read naively (local as UTC), most fills land 4-5h early.
select f.form_fill_id, f.submitted_at, s.session_start_at
from {{ ref('stg_form_fills') }} f
join {{ ref('stg_web_sessions') }} s using (session_id)
where f.submitted_at < s.session_start_at
   or f.submitted_at > s.session_start_at + interval 1 hour
