-- Hourly sector % change weighted by market cap.
-- Market caps live in a small CTE; refresh quarterly. Values in USD billions.

{{ config(materialized='table') }}

with mcap as (
    select * from (values
        ('NVDA',3300),('AAPL',3400),('MSFT',3100),('AVGO',780),('CRM',290),
        ('ORCL',430),('ADBE',230),('AMD',260),('CSCO',200),('INTC',130),
        ('JPM',620),('BRK.B',1000),('V',570),('MA',460),('BAC',310),
        ('WFC',210),('GS',170),('MS',170),('C',130),('BLK',150),
        ('LLY',780),('JNJ',380),('UNH',470),('ABBV',310),('MRK',300),
        ('TMO',220),('AMGN',170),('PFE',160),('ABT',200),('DHR',180),
        ('AMZN',2000),('TSLA',780),('HD',360),('MCD',210),('NKE',120),
        ('LOW',150),('SBUX',110),('BKNG',130),('TJX',130),('CMG',90),
        ('GOOGL',2200),('META',1400),('NFLX',300),('DIS',180),('TMUS',230),
        ('VZ',180),('CMCSA',170),('T',130),('WBD',25),('CHTR',55),
        ('CAT',180),('GE',180),('RTX',150),('UNP',140),('HON',140),
        ('LMT',120),('UPS',120),('DE',110),('BA',120),('FDX',70),
        ('WMT',650),('COST',400),('PG',390),('KO',280),('PEP',230),
        ('PM',180),('MDLZ',95),('MO',90),('TGT',70),('CL',80),
        ('XOM',490),('CVX',280),('COP',135),('SLB',65),('EOG',75),
        ('MPC',55),('PSX',60),('VLO',45),('OXY',55),('HAL',30),
        ('NEE',150),('DUK',85),('SO',95),('CEG',80),('D',45),
        ('AEP',55),('SRE',55),('PCG',45),('EXC',40),('VST',45),
        ('PLD',110),('AMT',95),('EQIX',75),('WELL',75),('SPG',60),
        ('CCI',50),('PSA',55),('O',50),('DRE',25),('CSGP',30),
        ('LIN',220),('FCX',70),('SHW',95),('APD',60),('ECL',65),
        ('NEM',55),('DOW',40),('NUE',35),('CTVA',45),('VMC',35)
    ) as t(ticker, market_cap_b)
),

-- For each bar, compute symbol % change vs the prior bar.
with_lag as (
    select
        symbol,
        sector,
        bar_ts,
        close,
        lag(close) over (partition by symbol order by bar_ts) as prev_close
    from {{ ref('silver_stock_prices') }}
),

pct as (
    select
        symbol, sector, bar_ts,
        (close - prev_close) / nullif(prev_close, 0) as pct_change
    from with_lag
    where prev_close is not null
)

select
    p.bar_ts,
    p.sector,
    sum(p.pct_change * m.market_cap_b) / nullif(sum(m.market_cap_b), 0) as sector_pct_change,
    count(distinct p.symbol) as n_tickers
from pct p
join mcap m on m.ticker = p.symbol
where p.sector is not null
group by 1, 2
order by 1 desc, 2
