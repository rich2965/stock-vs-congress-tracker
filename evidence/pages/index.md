---
title: Sector Performance vs. Political Trades
---

## Hourly sector performance (last 24h)

```sql sector_perf
select
  bar_ts,
  sector,
  sector_pct_change * 100 as pct_change
from stock_tracker.gold.gold_sector_hourly_perf
where bar_ts >= current_timestamp - interval '24 hours'
order by bar_ts
```

<LineChart
  data={sector_perf}
  x=bar_ts
  y=pct_change
  series=sector
  yAxisTitle="% change"
/>

## Congressional buy volume by sector (last 30d)

```sql buys_30d
select
  sector,
  est_buy_volume_30d_by_report / 1000 as est_buy_volume_30d_k
from stock_tracker.gold.gold_sector_congress_buys_30d
order by est_buy_volume_30d_k desc
```

<BarChart
  data={buys_30d}
  x=sector
  y=est_buy_volume_30d_k
  yAxisTitle="Est. $ (thousands)"
  swapXY=true
/>

## Recent late filings

```sql late_filings
select
  member, chamber, ticker, sector, trade_date, report_date, disclosure_lag_days
from stock_tracker.silver.silver_congress_trades
where is_late_disclosure
order by report_date desc
limit 25
```

<DataTable data={late_filings} />
