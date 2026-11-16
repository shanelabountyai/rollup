-- Q: Which five paid campaigns were the first touch for the most leads?
-- ordered: true
select c.campaign_name, count(*) as first_touches
from marts.fct_touches as t
join marts.dim_campaign as c on c.campaign_id = t.campaign_id
where t.is_first_touch
group by c.campaign_name
order by first_touches desc, c.campaign_name
limit 5
