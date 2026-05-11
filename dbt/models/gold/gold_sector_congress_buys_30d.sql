-- Total Congressional 'Buy' volume per sector, trailing 30 days.
-- Two views: by report_date (what's been disclosed) and trade_date (what actually happened).

{{ config(materialized='table') }}

with buys as (
    select *
    from {{ ref('silver_congress_trades') }}
    where lower(txn_type) like 'purchase%'   -- "Purchase", "Purchase (Partial)"
       or lower(txn_type) like 'buy%'
)

select
    sector,
    count(*)                                                     as n_trades,
    sum(est_trade_value_usd)                                     as est_buy_volume_usd,
    sum(case when report_date >= current_date - interval 30 day
             then est_trade_value_usd else 0 end)                as est_buy_volume_30d_by_report,
    sum(case when trade_date  >= current_date - interval 30 day
             then est_trade_value_usd else 0 end)                as est_buy_volume_30d_by_trade,
    avg(disclosure_lag_days)                                     as avg_disclosure_lag_days,
    sum(case when is_late_disclosure then 1 else 0 end)          as n_late_filings
from buys
where sector is not null
group by sector
order by est_buy_volume_30d_by_report desc
