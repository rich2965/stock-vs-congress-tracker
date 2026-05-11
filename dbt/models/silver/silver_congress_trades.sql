-- Flatten House + Senate Stock Watcher arrays into a unified trade fact.
-- Schemas differ slightly: House uses "representative", Senate uses "senator".
-- Both expose: transaction_date, disclosure_date, ticker, type, amount, owner.

{{ config(materialized='table') }}

with raw as (
    select source, extracted_at, payload
    from {{ source('bronze', 'raw_congress_trades') }}
),

exploded as (
    select
        r.source,
        r.extracted_at,
        unnest(cast(r.payload as json[])) as trade
    from raw r
),

parsed as (
    select
        source,
        coalesce(trade ->> 'representative', trade ->> 'senator') as member,
        upper(trade ->> 'ticker')                                  as ticker,
        trade ->> 'type'                                           as txn_type,
        trade ->> 'amount'                                         as txn_amount,
        trade ->> 'owner'                                          as owner,
        try_cast(trade ->> 'transaction_date' as date)             as trade_date,
        try_cast(trade ->> 'disclosure_date'  as date)             as report_date,
        extracted_at
    from exploded
    -- Filter junk tickers (HSW has "--", "N/A", empty strings)
    where trade ->> 'ticker' is not null
      and trade ->> 'ticker' not in ('--', 'N/A', '')
),

-- Dedup on natural key; keep latest extraction
deduped as (
    select * exclude (rn) from (
        select *,
               row_number() over (
                   partition by source, member, ticker, trade_date, txn_type, txn_amount
                   order by extracted_at desc
               ) as rn
        from parsed
    ) where rn = 1
),

-- Parse "$1,001 - $15,000" → low/high/midpoint
sized as (
    select
        *,
        try_cast(replace(replace(trim(split_part(txn_amount, '-', 1)), '$',''),',','') as double) as range_low,
        try_cast(replace(replace(trim(split_part(txn_amount, '-', 2)), '$',''),',','') as double) as range_high
    from deduped
),

sectors as (select ticker, sector from {{ ref('dim_sectors') }})

select
    s.source,
    s.member,
    s.ticker,
    sec.sector,
    s.owner,
    s.txn_type,
    s.trade_date,
    s.report_date,
    date_diff('day', s.trade_date, s.report_date) as disclosure_lag_days,
    -- STOCK Act gives members 45 days; flag late filings
    case when date_diff('day', s.trade_date, s.report_date) > 45 then true else false end as is_late_disclosure,
    s.range_low,
    s.range_high,
    coalesce((s.range_low + s.range_high) / 2.0, s.range_low, s.range_high) as est_trade_value_usd,
    s.extracted_at
from sized s
left join sectors sec on sec.ticker = s.ticker
where s.trade_date is not null
