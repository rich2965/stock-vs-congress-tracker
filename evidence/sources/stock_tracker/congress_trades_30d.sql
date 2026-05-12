-- Individual congressional trades over the last 30 days.
-- Untracked tickers (not in dim_sectors) are bucketed as 'Other'.
select
    member,
    chamber,
    party,
    ticker,
    issuer,
    coalesce(sector, 'Other') as sector,
    txn_type,
    trade_date,
    report_date,
    est_trade_value_usd,
    case
      when ticker is not null and ticker not in ('', '--', 'N/A')
      then 'https://finance.yahoo.com/quote/' || replace(ticker, '.', '-')
      else null
    end as yahoo_url
from main_silver.silver_congress_trades
where trade_date >= current_date - interval '30 days'
order by trade_date desc
