---
title: Sector Performance vs. Political Trades
description: Daily-refreshed view of US sector performance alongside Congressional buying activity.
---

```sql sector_perf
select * from stock_tracker.sector_perf
```

```sql stock_perf
select * from stock_tracker.sector_stock_perf
```

```sql buys_30d
select * from stock_tracker.buys_30d
```

```sql trades_30d
select * from stock_tracker.congress_trades_30d
```

```sql totals
select
  (select count(distinct sector) from stock_tracker.sector_perf) as sectors_tracked,
  (select sum(est_buy_volume_30d_k) * 1000 from stock_tracker.buys_30d) as total_buy_volume_usd
```

<Grid cols=2>
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
</Grid>

## Hourly sector performance — last 24 hours

Market-cap-weighted hourly % change per sector. Pick a sector to drill into individual tickers.

<Dropdown
  name=perf_sector
  data={sector_perf}
  value=sector
  defaultValue="%"
  title="Sector"
>
  <DropdownOption value="%" valueLabel="All sectors" />
</Dropdown>

```sql perf_filtered
select * from ${sector_perf}
where sector like '${inputs.perf_sector.value}'
order by bar_ts
```

<LineChart
  data={perf_filtered}
  x=bar_ts
  y=pct_change
  series=sector
  yFmt=pct2
  xFmt='MMM D ha'
  yAxisTitle="% change"
  xAxisTitle=""
  chartAreaHeight=320
/>

<Accordion>
  <AccordionItem title="Show per-ticker breakdown for selected sector">

```sql ticker_filtered
select symbol, sector, bar_ts, close, pct_change
from ${stock_perf}
where sector like '${inputs.perf_sector.value}'
order by bar_ts desc, symbol
```

<DataTable data={ticker_filtered} rows=20 search=true>
  <Column id=symbol title="Ticker" />
  <Column id=sector title="Sector" />
  <Column id=bar_ts title="Hour" />
  <Column id=close title="Close" fmt=usd2 align=right />
  <Column id=pct_change title="% change" fmt=pct2 align=right contentType=colorscale colorScale=diverging />
</DataTable>

  </AccordionItem>
</Accordion>

## Congressional buy volume by sector — last 30 days

Estimated USD volume of "buy" trades disclosed by Congress over the last 30 days. Pick a sector to see exactly which trades drove the number — including any stocks outside our 110-ticker watchlist (bucketed as "Other").

<Dropdown
  name=trade_sector
  data={buys_30d}
  value=sector
  defaultValue="%"
  title="Sector"
>
  <DropdownOption value="%" valueLabel="All sectors" />
</Dropdown>

```sql buys_filtered
select * from ${buys_30d}
where sector like '${inputs.trade_sector.value}'
order by est_buy_volume_30d_k desc
```

<BarChart
  data={buys_filtered}
  x=sector
  y=est_buy_volume_30d_k
  yAxisTitle="Est. $ (thousands)"
  swapXY=true
  sort=false
  chartAreaHeight=400
/>

<Accordion>
  <AccordionItem title="Show individual trades for selected sector">

```sql trades_filtered
select * from ${trades_30d}
where sector like '${inputs.trade_sector.value}'
order by trade_date desc
```

<DataTable data={trades_filtered} rows=25 search=true>
  <Column id=member title="Member" />
  <Column id=chamber title="Chamber" />
  <Column id=ticker title="Ticker" />
  <Column id=issuer title="Company" />
  <Column id=sector title="Sector" />
  <Column id=txn_type title="Type" />
  <Column id=trade_date title="Traded" />
  <Column id=est_trade_value_usd title="Est. $" fmt=usd0 align=right />
</DataTable>

  </AccordionItem>
</Accordion>

---

<small>
  Data sources: <a href="https://finance.yahoo.com">Yahoo Finance</a> (hourly OHLCV via yfinance) &middot; <a href="https://www.capitoltrades.com/trades">Capitol Trades</a> (Congressional disclosures, scraped).
  Pipeline: Python → MotherDuck → dbt → Evidence. Refreshed daily after US market close.
</small>
