---
title: Sector Performance vs. Political Trades
description: Hourly US sector performance side-by-side with Congressional buying activity.
---

```sql sector_perf
select * from stock_tracker.sector_perf
```

```sql buys_30d
select * from stock_tracker.buys_30d
```

```sql late_filings
select * from stock_tracker.late_filings
```

```sql totals
select
  (select count(distinct sector) from stock_tracker.sector_perf) as sectors_tracked,
  (select sum(est_buy_volume_30d_k) * 1000 from stock_tracker.buys_30d) as total_buy_volume_usd,
  (select count(*) from stock_tracker.late_filings) as late_filings_count
```

<Grid cols=3>
  <BigValue
    data={totals}
    value=sectors_tracked
    title="Sectors tracked"
  />
  <BigValue
    data={totals}
    value=total_buy_volume_usd
    title="Congressional buy volume (30d)"
    fmt=usd0
  />
  <BigValue
    data={totals}
    value=late_filings_count
    title="Late filings (>45 days)"
  />
</Grid>

## Hourly sector performance — last 24 hours

Market-cap-weighted % change per sector, refreshed hourly via Alpha-replacement (yfinance) into MotherDuck.

<LineChart
  data={sector_perf}
  x=bar_ts
  y=pct_change
  series=sector
  yAxisTitle="% change"
  xAxisTitle="Hour"
  chartAreaHeight=320
/>

## Congressional buy volume by sector — last 30 days

Estimated USD volume of "buy" trades disclosed by Congress over the last 30 days, sourced from Capitol Trades and bucketed into S&P 500 sectors.

<BarChart
  data={buys_30d}
  x=sector
  y=est_buy_volume_30d_k
  yAxisTitle="Est. $ (thousands)"
  swapXY=true
  sort=false
  chartAreaHeight=400
/>

## Recently disclosed late filings

Trades disclosed more than 45 days after execution (the STOCK Act limit).

<DataTable data={late_filings} rows=15 search=true>
  <Column id=member title="Member" />
  <Column id=chamber title="Chamber" />
  <Column id=ticker title="Ticker" />
  <Column id=sector title="Sector" />
  <Column id=trade_date title="Traded" />
  <Column id=report_date title="Disclosed" />
  <Column id=disclosure_lag_days title="Days late" align=right contentType=colorscale colorScale=negative />
</DataTable>

---

<small>
  Data sources: <a href="https://finance.yahoo.com">Yahoo Finance</a> (hourly OHLCV via yfinance) &middot; <a href="https://www.capitoltrades.com/trades">Capitol Trades</a> (Congressional disclosures, scraped hourly).
  Pipeline: Python → MotherDuck → dbt → Evidence. Refreshed every hour.
</small>
