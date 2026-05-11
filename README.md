# Sector Performance vs. Political Trades

End-to-end pipeline: Python extraction → MotherDuck (Bronze/Silver/Gold) → dbt → Evidence on GitHub Pages. Runs hourly via GitHub Actions.

## Architecture

```
yfinance              ─┐
                       ├─► fetch_market_data.py ─► MotherDuck.bronze.*  (append-only JSON)
Capitol Trades API    ─┘                                  │
                                                          ▼
                                                  dbt silver  (cleaned, sector-joined, deduped)
                                                          │
                                                          ▼
                                                  dbt gold   (sector hourly perf, 30d congress buys)
                                                          │
                                                          ▼
                                                  Evidence.dev  → GitHub Pages
```

All sources are free / public, no API keys required.

### Scaffolding Evidence (one-time)

The workflow auto-skips the Evidence build/deploy steps until `evidence/package.json` exists. To set it up:

```bash
npx degit evidence-dev/template evidence
cd evidence
npm install
# add a MotherDuck source in evidence/sources/ (see Evidence docs)
```

Commit the `evidence/` folder and the next workflow run will build and publish to `gh-pages`.

## Deploy

1. **MotherDuck**: create a database called `stock_tracker`. Grab a service token.
2. **Repo secret** (Settings → Secrets and variables → Actions): `MOTHERDUCK_TOKEN`.
3. **Enable GitHub Pages** (Settings → Pages → Source: `gh-pages` branch).
4. Push. The workflow runs hourly at `:05` and on demand via *Actions → Run workflow*.

Local run:
```bash
pip install -r requirements.txt
export MOTHERDUCK_TOKEN=...
python fetch_market_data.py
cd dbt && dbt deps && dbt seed && dbt build
```

## Data Quality

| Layer | Guarantee |
|---|---|
| Bronze | Raw JSON preserved verbatim with `extracted_at` — replayable, never mutated. |
| Silver | Dedup via `row_number() over (partition by natural_key order by extracted_at desc)`. Type casts wrapped in `try_cast` so a bad row never poisons the table. Sectors backfilled via `dim_sectors` seed; nulls surfaced (not dropped). |
| Gold   | `dbt test` enforces not-null + uniqueness on grain. CI fails the run on any test failure (`--fail-fast`). |

**Congressional 45-day lag.** The STOCK Act gives members 45 days to disclose. `silver_congress_trades` exposes both `trade_date` (when it happened) and `report_date` (when we learned), plus `disclosure_lag_days` and an `is_late_disclosure` flag. The 30-day gold metric is computed two ways — `by_report` for "what hit the news this month" and `by_trade` for "what was actually executed this month" — so dashboards can show both without re-asking the warehouse.

## Idempotency

- **Bronze is append-only** keyed by `extracted_at`. Re-running the extractor never overwrites, only adds.
- **Silver/Gold are full-refresh `table` materializations** that dedup from bronze. Running the pipeline N times in the same hour yields the same gold output — duplicates collapse in the silver `row_number` step.
- **GitHub Actions `concurrency`** group prevents two pipelines stomping on each other; `cancel-in-progress: false` lets the prior run finish cleanly (safe because of the above).
- **Alpha Vantage throttling** is handled in-script (~13s sleep ≈ 5 req/min). Throttled tickers are logged but don't fail the run; next hour's extraction backfills.

## Models

| Model | Purpose |
|---|---|
| `silver_stock_prices` | Hourly OHLCV, deduped, joined to sector. |
| `silver_congress_trades` | Flattened trades w/ disclosure lag + estimated $ value (midpoint of disclosed range). |
| `gold_sector_hourly_perf` | Hourly % change per sector, market-cap weighted. |
| `gold_sector_congress_buys_30d` | Trailing-30d congressional Buy volume per sector, both by report_date and trade_date. |

## Notes

- Market caps in `gold_sector_hourly_perf` are a static CTE — refresh quarterly or wire to a `dim_securities` source.
- yfinance pulls `period=1mo`, `interval=1h` per run. Hourly bars are only available for the trailing ~730 days from Yahoo, which is fine here.
- `BRK.B` is normalized to `BRK-B` when calling Yahoo (yfinance share-class convention).
- `DRE` (Real Estate) merged into Prologis in 2022 — leaving the seed entry as a placeholder; expect null prices for that ticker.
- House + Senate Stock Watcher are static S3 dumps refreshed by the maintainers; nothing to authenticate.
