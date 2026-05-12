---
title: Sector Performance vs. Political Trades
description: Daily US sector performance alongside Congressional buying activity, refreshed after market close.
---

```sql sector_perf
select * from stock_tracker.sector_perf
```

```sql stock_perf
select * from stock_tracker.sector_stock_perf
```

```sql trades_30d
select * from stock_tracker.congress_trades_30d
```

```sql totals
select
  (select count(distinct sector) from stock_tracker.sector_perf) as sectors_tracked,
  (select sum(est_trade_value_usd) from stock_tracker.congress_trades_30d where txn_type = 'buy') as total_buy_volume_usd
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

## Daily sector performance — last 30 days

Market-cap-weighted daily % change per sector. Hourly bars compounded into daily returns.

<Dropdown
  name=perf_sectors
  data={sector_perf}
  value=sector
  multiple=true
  selectAllByDefault=true
  title="Sectors"
/>

```sql perf_filtered
select * from ${sector_perf}
where sector in ${inputs.perf_sectors.value}
order by trade_date
```

<LineChart
  data={perf_filtered}
  x=trade_date
  y=pct_change
  series=sector
  yFmt=pct2
  xFmt='MMM D'
  yAxisTitle="% change"
  xAxisTitle=""
  chartAreaHeight=320
/>

<Accordion>
  <AccordionItem title="Show per-ticker breakdown for selected sectors">

```sql tickers_in_sectors
select distinct symbol, company_name
from ${stock_perf}
where sector in ${inputs.perf_sectors.value}
order by symbol
```

<Dropdown
  name=perf_tickers
  data={tickers_in_sectors}
  value=symbol
  label=symbol
  multiple=true
  selectAllByDefault=true
  title="Tickers"
/>

```sql ticker_filtered
select symbol, company_name, sector, trade_date, close, pct_change, yahoo_url
from ${stock_perf}
where sector in ${inputs.perf_sectors.value}
  and symbol in ${inputs.perf_tickers.value}
order by trade_date desc, symbol
```

<DataTable data={ticker_filtered} rows=20 search=true>
  <Column id=yahoo_url title="Ticker" contentType=link linkLabel=symbol openInNewTab=true />
  <Column id=company_name title="Company" />
  <Column id=sector title="Sector" />
  <Column id=trade_date title="Date" />
  <Column id=close title="Close" fmt=usd2 align=right />
  <Column id=pct_change title="% change" fmt=pct2 align=right contentType=colorscale colorScale=diverging />
</DataTable>

  </AccordionItem>
</Accordion>

## Congressional buy volume by sector — last 30 days

Filter sectors and minimum trade size. Stocks outside our tracked watchlist are bucketed as "Other".

<Grid cols=2>
  <Dropdown
    name=trade_sectors
    data={trades_30d}
    value=sector
    multiple=true
    selectAllByDefault=true
    title="Sectors"
  />
  <Dropdown name=min_size title="Min trade size">
    <DropdownOption value=0        valueLabel="All" />
    <DropdownOption value=15000    valueLabel="≥ $15K" />
    <DropdownOption value=50000    valueLabel="≥ $50K" />
    <DropdownOption value=100000   valueLabel="≥ $100K" />
    <DropdownOption value=250000   valueLabel="≥ $250K" />
    <DropdownOption value=1000000  valueLabel="≥ $1M" />
  </Dropdown>
</Grid>

```sql buys_filtered
select
  sector,
  count(*) as n_trades,
  sum(est_trade_value_usd) / 1000.0 as est_buy_volume_30d_k
from ${trades_30d}
where txn_type = 'buy'
  and sector in ${inputs.trade_sectors.value}
  and coalesce(est_trade_value_usd, 0) >= ${inputs.min_size.value}
group by sector
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
  <AccordionItem title="Show individual trades for selected filters">

```sql trades_filtered
select * from ${trades_30d}
where txn_type = 'buy'
  and sector in ${inputs.trade_sectors.value}
  and coalesce(est_trade_value_usd, 0) >= ${inputs.min_size.value}
order by est_trade_value_usd desc nulls last, trade_date desc
```

<DataTable data={trades_filtered} rows=25 search=true>
  <Column id=member title="Member" />
  <Column id=chamber title="Chamber" />
  <Column id=yahoo_url title="Ticker" contentType=link linkLabel=ticker openInNewTab=true />
  <Column id=issuer title="Company" />
  <Column id=sector title="Sector" />
  <Column id=trade_date title="Date" />
  <Column id=est_trade_value_usd title="Est. $" fmt=usd0 align=right />
</DataTable>

  </AccordionItem>
</Accordion>

---

<small>
  Data sources: <a href="https://finance.yahoo.com">Yahoo Finance</a> (hourly OHLCV via yfinance, rolled up to daily) &middot; <a href="https://www.capitoltrades.com/trades">Capitol Trades</a> (Congressional disclosures, scraped).
  Pipeline: Python → MotherDuck → dbt → Evidence. Refreshed daily after US market close.
</small>
