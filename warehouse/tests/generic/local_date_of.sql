{#
  D-15: a reporting date column must be the local_tz calendar date of its UTC timestamp.
  Fails on any row where the two disagree (e.g. a model that used `ts::date`, i.e. the UTC day).
#}
{% test local_date_of(model, column_name, timestamp_column) %}
select *
from {{ model }}
where {{ timestamp_column }} is not null
  and {{ column_name }} is distinct from {{ local_date(timestamp_column) }}
{% endtest %}
