-- Parse Capitol Trades scraped rows into a tidy trade fact.
-- Bronze payload = JSON array of {text: [[...cell_lines...], ...], ticker: "NVDA"}
-- Column order observed on capitoltrades.com/trades (left → right):
--   0: Politician (multiline: name / "Republican|Democrat" / "House|Senate")
--   1: Traded Issuer (company / ticker)
--   2: Published date
--   3: Traded date     ("16 Apr 2024")
--   4: Filed after     ("3 days", "45 days", ...)
--   5: Owner
--   6: Type            ("buy" | "sell" | "exchange" | "receive")
--   7: Size            ("1K–15K", "15K–50K", ..., "50M+")
--   8: Price

{{ config(materialized='table') }}

with raw as (
    select source, extracted_at, payload
    from {{ source('bronze', 'raw_congress_trades') }}
),

exploded as (
    select
        r.source,
        r.extracted_at,
        unnest(cast(r.payload as json[])) as row
    from raw r
),

parsed as (
    select
        source,

        -- Politician cell: line 0 = name, line 1 = party, line 2 = chamber (may vary)
        cast(row -> '$.text[0][0]' as varchar) as member,
        lower(cast(row -> '$.text[0][1]' as varchar)) as party,
        lower(cast(row -> '$.text[0][2]' as varchar)) as chamber,

        -- Ticker comes from the <a href="/stocks/XYZ"> attribute we captured separately
        upper(coalesce(cast(row -> '$.ticker' as varchar),
                       cast(row -> '$.text[1][1]' as varchar))) as ticker,

        -- Dates: "16 Apr 2024"
        try_strptime(cast(row -> '$.text[2][0]' as varchar), '%d %b %Y')::date as report_date,
        try_strptime(cast(row -> '$.text[3][0]' as varchar), '%d %b %Y')::date as trade_date,

        cast(row -> '$.text[5][0]' as varchar)         as owner,
        lower(cast(row -> '$.text[6][0]' as varchar))  as txn_type,
        cast(row -> '$.text[7][0]' as varchar)         as txn_value_band,

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

-- Dedup by natural key (no stable txId from scrape → composite key)
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

-- Capitol Trades value bands → USD midpoints
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
        end as est_trade_value_usd
    from deduped
),

sectors as (select ticker, sector from {{ ref('dim_sectors') }})

select
    s.source,
    s.member,
    s.chamber,
    s.party,
    s.ticker,
    sec.sector,
    s.owner,
    s.txn_type,
    s.trade_date,
    s.report_date,
    date_diff('day', s.trade_date, s.report_date) as disclosure_lag_days,
    case when date_diff('day', s.trade_date, s.report_date) > 45 then true else false end as is_late_disclosure,
    s.txn_value_band,
    s.est_trade_value_usd,
    s.extracted_at
from sized s
left join sectors sec on sec.ticker = s.ticker
