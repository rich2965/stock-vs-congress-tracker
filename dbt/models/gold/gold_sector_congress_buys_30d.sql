-- Total Congressional 'Buy' volume per sector over the last 30 days.
-- Untracked tickers (not in dim_sectors) are bucketed as 'Other' so we
-- don't drop signal — Congress trades plenty of names outside our 110.

{{ config(materialized='table') }}

with buys as (
    select *
    from {{ ref('silver_congress_trades') }}
    where txn_type = 'buy'
),

bucketed as (
    select
        coalesce(sector, 'Other') as sector,
        est_trade_value_usd,
        trade_date,
        report_date,
        disclosure_lag_days,
        is_late_disclosure
    from buys
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
from bucketed
group by sector
order by est_buy_volume_30d_by_report desc
