---
title: Sector Performance vs. Political Trades
---

## Hourly sector performance (last 24h)

```sql sector_perf
select * from stock_tracker.sector_perf
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
select * from stock_tracker.buys_30d
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
select * from stock_tracker.late_filings
```

<DataTable data={late_filings} />
