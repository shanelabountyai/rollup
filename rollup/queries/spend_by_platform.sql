-- Q: What is total spend, CPC and CTR by ad platform over the whole period?
select
    platform,
    sum(spend_usd) as spend_usd,
    sum(impressions) as impressions,
    sum(clicks) as clicks,
    round(sum(spend_usd) / nullif(sum(clicks), 0), 2) as cpc_usd,
    round(100.0 * sum(clicks) / nullif(sum(impressions), 0), 3) as ctr_pct
from marts.fct_spend
group by platform
order by spend_usd desc
