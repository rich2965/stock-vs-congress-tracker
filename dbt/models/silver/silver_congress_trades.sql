-- Capitol Trades scraped trades → tidy fact table.
-- Bronze payload = JSON array of objects (one per trade row), with fields verified live:
--   politician, party, chamber, state, issuer, ticker, trade_date_raw ("22 Apr 2026"),
--   filed_after_days (int), owner, tx_type ('buy'|'sell'|'exchange'), size, price.
-- report_date is computed as trade_date + filed_after_days (Capitol Trades doesn't expose
-- the actual filing date in absolute form on the list view — it shows "X days").

{{ config(materialized='table') }}

with raw as (
    select source, extracted_at, payload
    from {{ source('bronze', 'raw_congress_trades') }}
),

exploded as (
    select
        r.source,
        r.extracted_at,
        unnest(cast(r.payload as json[])) as t
    from raw r
),

parsed as (
    select
        source,
        cast(t ->> 'politician' as varchar) as member,
        lower(cast(t ->> 'party'   as varchar)) as party,
        lower(cast(t ->> 'chamber' as varchar)) as chamber,
        cast(t ->> 'state'     as varchar) as state,
        cast(t ->> 'issuer'    as varchar) as issuer,
        upper(cast(t ->> 'ticker' as varchar)) as ticker,

        try_strptime(cast(t ->> 'trade_date_raw' as varchar), '%d %b %Y')::date as trade_date,
        try_cast(t ->> 'filed_after_days' as integer) as disclosure_lag_days,

        cast(t ->> 'owner'   as varchar) as owner,
        lower(cast(t ->> 'tx_type' as varchar)) as txn_type,
        cast(t ->> 'size'    as varchar) as txn_value_band,
        cast(t ->> 'price'   as varchar) as price,

        extracted_at
    from exploded
),

filtered as (
    select *
    from parsed
    where ticker is not null
      and ticker not in ('', '--', 'N/A')
      and trade_date is not null
),

-- Dedup on natural key
deduped as (
    select * exclude (rn) from (
        select *,
               row_number() over (
                   partition by member, ticker, trade_date, txn_type, txn_value_band
                   order by extracted_at desc
               ) as rn
        from filtered
    ) where rn = 1
),

-- Map Capitol Trades size bands → USD midpoints
sized as (
    select
        *,
        case txn_value_band
            when '1K–15K'    then 8000
            when '15K–50K'   then 32500
            when '50K–100K'  then 75000
            when '100K–250K' then 175000
            when '250K–500K' then 375000
            when '500K–1M'   then 750000
            when '1M–5M'     then 3000000
            when '5M–25M'    then 15000000
            when '25M–50M'   then 37500000
            when '50M+'      then 50000000
            else null
        end as est_trade_value_usd,
        trade_date + (coalesce(disclosure_lag_days, 0) || ' days')::interval as report_date_calc
    from deduped
),

sectors as (select ticker, sector from {{ ref('dim_sectors') }})

select
    s.source,
    s.member,
    s.chamber,
    s.party,
    s.state,
    s.issuer,
    s.ticker,
    sec.sector,
    s.owner,
    s.txn_type,
    s.trade_date,
    cast(s.report_date_calc as date) as report_date,
    s.disclosure_lag_days,
    case when coalesce(s.disclosure_lag_days, 0) > 45 then true else false end as is_late_disclosure,
    s.txn_value_band,
    s.est_trade_value_usd,
    s.price,
    s.extracted_at
from sized s
left join sectors sec on sec.ticker = s.ticker
