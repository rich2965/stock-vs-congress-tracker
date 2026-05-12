-- Daily sector performance over the last 30 days.
-- Compounds the hourly returns from gold.gold_sector_hourly_perf using
-- exp(sum(ln(1+r))) - 1, which is the mathematically correct way to roll
-- hourly returns up to daily.
select
  date_trunc('day', bar_ts)::date as trade_date,
  sector,
  exp(sum(ln(1 + coalesce(sector_pct_change, 0)))) - 1 as pct_change
from main_gold.gold_sector_hourly_perf
where bar_ts >= current_date - interval '30 days'
  and coalesce(sector_pct_change, 0) > -0.99   -- guard ln(0)
group by 1, 2
order by 1, 2
