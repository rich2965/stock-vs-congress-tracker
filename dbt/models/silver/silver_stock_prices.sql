-- Unnest the yfinance bars array into a tidy hourly OHLCV fact, deduped, joined to sector.

{{ config(materialized='table') }}

with raw as (
    select symbol, extracted_at, payload
    from {{ source('bronze', 'raw_stock_prices') }}
),

-- Explode the "bars" array. Each element: {ts, open, high, low, close, volume}
exploded as (
    select
        r.symbol,
        r.extracted_at,
        unnest(cast(r.payload -> '$.bars' as json[])) as bar
    from raw r
),

parsed as (
    select
        symbol,
        cast(bar ->> 'ts' as timestamp) as bar_ts,
        cast(bar ->> 'open'   as double) as open,
        cast(bar ->> 'high'   as double) as high,
        cast(bar ->> 'low'    as double) as low,
        cast(bar ->> 'close'  as double) as close,
        cast(bar ->> 'volume' as bigint) as volume,
        extracted_at
    from exploded
),

-- Keep latest extraction per (symbol, bar_ts)
deduped as (
    select * exclude (rn) from (
        select *, row_number() over (partition by symbol, bar_ts order by extracted_at desc) as rn
        from parsed
    ) where rn = 1
),

sectors as (select ticker, sector from {{ ref('dim_sectors') }})

select
    d.symbol,
    s.sector,
    d.bar_ts,
    d.open, d.high, d.low, d.close, d.volume,
    d.extracted_at
from deduped d
left join sectors s on s.ticker = d.symbol
where d.close is not null
