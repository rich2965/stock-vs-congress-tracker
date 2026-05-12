-- Per-ticker hourly performance over the last 24h.
-- Used for the per-sector drill-down table.
with with_lag as (
    select
        symbol,
        sector,
        bar_ts,
        close,
        lag(close) over (partition by symbol order by bar_ts) as prev_close
    from main_silver.silver_stock_prices
    where bar_ts >= current_timestamp - interval '24 hours'
)
select
    symbol,
    sector,
    bar_ts,
    close,
    (close - prev_close) / nullif(prev_close, 0) as pct_change
from with_lag
where prev_close is not null
  and sector is not null
order by symbol, bar_ts
