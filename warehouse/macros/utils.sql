{#
  Defect fixes live in these macros. The `unfix` var switches one fix off so the mutation
  test (tests/test_defect_detection.py) can prove the matching custom dbt test fails.
  Never set it outside that test.
#}

{# D1: canonical form for UTM-style strings: trimmed, lower-cased, empty -> null. #}
{% macro clean_str(col) -%}
    {%- if var('unfix', '') == 'D1' -%}{{ col }}{%- else -%}nullif(lower(trim({{ col }})), ''){%- endif -%}
{%- endmacro %}

{# Campaign name -> UTM key, mirroring how the marketing team builds utm_campaign. #}
{% macro slugify(col) -%}
    trim(regexp_replace(lower(trim({{ col }})), '[^a-z0-9]+', '-', 'g'), '-')
{%- endmacro %}

{# D2: identity key for a person = hash of the normalised email. #}
{% macro person_key(email_col) -%}
    {%- if var('unfix', '') == 'D2' -%}md5({{ email_col }}){%- else -%}md5(lower(trim({{ email_col }}))){%- endif -%}
{%- endmacro %}

{# Reporting calendar (D-15): UTC timestamp -> business date in local_tz, matching ad-platform spend days. #}
{% macro local_date(utc_col) -%}
    cast(timezone('{{ var("local_tz") }}', timezone('UTC', {{ utc_col }})) as date)
{%- endmacro %}

{# D3: naive local wall-clock timestamp -> naive UTC timestamp. #}
{% macro local_to_utc(col) -%}
    {%- if var('unfix', '') == 'D3' -%}{{ col }}{%- else -%}timezone('UTC', timezone('{{ var("local_tz") }}', {{ col }})){%- endif -%}
{%- endmacro %}

