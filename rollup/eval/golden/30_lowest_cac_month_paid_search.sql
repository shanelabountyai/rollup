-- Q: Which month had the lowest first-touch CAC for paid search?
-- ordered: true
select month_start, cac_usd
from marts.mart_cac_by_channel
where channel_key = 'paid_search' and cac_usd is not null
order by cac_usd asc
limit 1
