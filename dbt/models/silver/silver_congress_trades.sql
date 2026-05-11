-- Flatten Capitol Trades JSON into a unified trade fact.
-- Source payload = JSON array; each element has nested `asset` and `politician` objects.
-- We code defensively (try_cast, coalesce) because the API shape can drift.

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
        cast(trade -> '$._txId' as varchar) as tx_id,

        -- Politician
        trim(coalesce(trade ->> '$.politician.politicianFirstName', '')
             || ' '
             || coalesce(trade ->> '$.politician.politicianFamilyName', '')) as member,
        lower(coalesce(trade ->> '$.politician.politicianType', '')) as chamber,
        trade ->> '$.politician.politicianParty' as party,

        -- Asset
        upper(coalesce(trade ->> '$.asset.assetTicker', '')) as ticker,
        trade ->> '$.asset.assetType' as asset_type,

        -- Transaction
        lower(coalesce(trade ->> '$.txType', '')) as txn_type,         -- 'buy' | 'sell' | 'exchange'
        trade ->> '$.txTypeExtended'              as txn_type_detail,  -- 'Purchase', 'Sale (Partial)', ...
        trade ->> '$.value'                       as txn_value_band,   -- '1K–15K', '15K–50K', ...
        trade ->> '$.owner'                       as owner,

        try_cast(trade ->> '$.txDate'      as date) as trade_date,
        try_cast(trade ->> '$.filingDate'  as date) as report_date,

        extracted_at
    from exploded
    where coalesce(trade ->> '$.asset.assetType', '') = 'stock'
      and trade ->> '$.asset.assetTicker' is not null
      and trade ->> '$.asset.assetTicker' not in ('', '--', 'N/A')
),

-- Dedup on natural key (Capitol Trades' _txId is unique per trade); fall back to a composite key.
deduped as (
    select * exclude (rn) from (
        select *,
               row_number() over (
                   partition by coalesce(tx_id, member || '|' || ticker || '|' || trade_date::varchar || '|' || txn_type)
                   order by extracted_at desc
               ) as rn
        from parsed
    ) where rn = 1
),

-- Map Capitol Trades value bands → numeric midpoints (USD).
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
    s.tx_id,
    s.member,
    s.chamber,
    s.party,
    s.ticker,
    sec.sector,
    s.owner,
    s.txn_type,
    s.txn_type_detail,
    s.trade_date,
    s.report_date,
    date_diff('day', s.trade_date, s.report_date) as disclosure_lag_days,
    case when date_diff('day', s.trade_date, s.report_date) > 45 then true else false end as is_late_disclosure,
    s.txn_value_band,
    s.est_trade_value_usd,
    s.extracted_at
from sized s
left join sectors sec on sec.ticker = s.ticker
where s.trade_date is not null
