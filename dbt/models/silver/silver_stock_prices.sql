-- Unnest Alpha Vantage JSON into a tidy hourly OHLCV fact, deduped, joined to sector.
-- Hardcoded market cap weights live in a CTE for simplicity (refresh quarterly).

{{ config(materialized='table') }}

with raw as (
    select
        symbol,
        extracted_at,
        payload
    from {{ source('bronze', 'raw_stock_prices') }}
),

-- Explode the "Time Series (60min)" object into rows
exploded as (
    select
        r.symbol,
        r.extracted_at,
        unnest(json_keys(r.payload -> '$."Time Series (60min)"')) as bar_ts_str,
        r.payload as p
    from raw r
    where r.payload -> '$."Time Series (60min)"' is not null
),

parsed as (
    select
        symbol,
        cast(bar_ts_str as timestamp) as bar_ts,
        cast(p -> ('$."Time Series (60min)"."' || bar_ts_str || '"."1. open"')   as double) as open,
        cast(p -> ('$."Time Series (60min)"."' || bar_ts_str || '"."2. high"')   as double) as high,
        cast(p -> ('$."Time Series (60min)"."' || bar_ts_str || '"."3. low"')    as double) as low,
        cast(p -> ('$."Time Series (60min)"."' || bar_ts_str || '"."4. close"')  as double) as close,
        cast(p -> ('$."Time Series (60min)"."' || bar_ts_str || '"."5. volume"') as bigint) as volume,
        extracted_at
    from exploded
),

-- Dedup: keep latest extraction per (symbol, bar_ts)
deduped as (
    select *
    from (
        select *,
               row_number() over (partition by symbol, bar_ts order by extracted_at desc) as rn
        from parsed
    )
    where rn = 1
),

sectors as (
    select ticker, sector from {{ ref('dim_sectors') }}
)

select
    d.symbol,
    s.sector,
    d.bar_ts,
    d.open, d.high, d.low, d.close, d.volume,
    d.extracted_at
from deduped d
left join sectors s on s.ticker = d.symbol
