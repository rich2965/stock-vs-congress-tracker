select
  member, chamber, ticker, sector, trade_date, report_date, disclosure_lag_days
from silver.silver_congress_trades
where is_late_disclosure = true
order by report_date desc
limit 25
