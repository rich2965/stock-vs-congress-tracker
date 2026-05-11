-- Flatten Quiver Quant array payload, dedup by natural key, join sector,
-- and model the 45-day STOCK Act disclosure lag explicitly.

{{ config(materialized='table') }}

with raw as (
    select
        extracted_at,
        unnest(cast(payload as json[])) as trade
    from {{ source('bronze', 'raw_congress_trades') }}
),

parsed as (
    select
        cast(trade ->> 'Representative' as varchar) as representative,
        cast(trade ->> 'Ticker'         as varchar) as ticker,
        cast(trade ->> 'Transaction'    as varchar) as txn_type,
        cast(trade ->> 'Range'          as varchar) as txn_range,
        cast(trade ->> 'TradeDate'      as date)    as trade_date,
        cast(trade ->> 'ReportDate'     as date)    as report_date,
        extracted_at
    from raw
),

deduped as (
    select *
    from (
        select *,
               row_number() over (
                   partition by representative, ticker, trade_date, txn_type, txn_range
                   order by extracted_at desc
               ) as rn
        from parsed
    )
    where rn = 1
),

-- Parse range strings like "$1,001 - $15,000" into numeric bounds; use midpoint as estimate.
sized as (
    select
        *,
        try_cast(replace(replace(split_part(txn_range, '-', 1), '$', ''), ',', '') as double) as range_low,
        try_cast(replace(replace(split_part(txn_range, '-', 2), '$', ''), ',', '') as double) as range_high
    from deduped
),

sectors as (select ticker, sector from {{ ref('dim_sectors') }})

select
    s.representative,
    s.ticker,
    sec.sector,
    s.txn_type,
    s.trade_date,
    s.report_date,
    date_diff('day', s.trade_date, s.report_date) as disclosure_lag_days,
    -- STOCK Act allows up to 45 days; flag late filings.
    case when date_diff('day', s.trade_date, s.report_date) > 45 then true else false end as is_late_disclosure,
    s.range_low,
    s.range_high,
    coalesce((s.range_low + s.range_high) / 2.0, s.range_low, s.range_high) as est_trade_value_usd,
    s.extracted_at
from sized s
left join sectors sec on sec.ticker = s.ticker
