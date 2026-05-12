select
  bar_ts,
  sector,
  sector_pct_change * 100 as pct_change
from main_gold.gold_sector_hourly_perf
where bar_ts >= current_timestamp - interval '24 hours'
order by bar_ts
