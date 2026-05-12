-- Per-ticker daily performance over the last 30 days.
-- Takes the last close of each calendar day from the hourly silver table.
with day_close as (
    select
        symbol,
        sector,
        bar_ts::date as trade_date,
        close,
        row_number() over (partition by symbol, bar_ts::date order by bar_ts desc) as rn
    from main_silver.silver_stock_prices
    where bar_ts >= current_date - interval '35 days'
      and sector is not null
),
eod as (
    select symbol, sector, trade_date, close
    from day_close
    where rn = 1
),
with_lag as (
    select
        symbol,
        sector,
        trade_date,
        close,
        lag(close) over (partition by symbol order by trade_date) as prev_close
    from eod
)
select
    symbol,
    sector,
    trade_date,
    close,
    (close - prev_close) / nullif(prev_close, 0) as pct_change
from with_lag
where prev_close is not null
  and trade_date >= current_date - interval '30 days'
order by trade_date desc, symbol
