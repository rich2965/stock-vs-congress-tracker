"""
Build dbt/seeds/dim_sectors.csv from public sources.

Layered approach:
  1) S&P 500 from Wikipedia        — ~504 tickers w/ official GICS Sector  (always)
  2) yfinance for "Other" tickers  — looks up sectors for any ticker Congress
                                     has actually traded that isn't on the S&P 500
                                     list (optional; requires MotherDuck creds)

Usage:
    pip install pandas lxml yfinance duckdb
    python scripts/refresh_dim_sectors.py            # S&P 500 only
    MOTHERDUCK_TOKEN=... python scripts/refresh_dim_sectors.py --backfill-other
                                                     # also resolve unknown tickers
    # then commit dbt/seeds/dim_sectors.csv
"""
import argparse, os, sys, time
from pathlib import Path
import pandas as pd

# Map GICS official sector names → the short labels already used by the project
SECTOR_MAP = {
    "Information Technology": "Tech",
    "Financials":              "Financials",
    "Health Care":             "Health Care",
    "Consumer Discretionary":  "Consumer Disc",
    "Communication Services":  "Comm Services",
    "Industrials":             "Industrials",
    "Consumer Staples":        "Staples",
    "Energy":                  "Energy",
    "Utilities":               "Utilities",
    "Real Estate":             "Real Estate",
    "Materials":               "Materials",
}

# yfinance returns full GICS sector names — same map works.
YF_SECTOR_MAP = dict(SECTOR_MAP)

UA_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dim-sectors-refresh)"}


def fetch_sp500() -> pd.DataFrame:
    """Scrape the S&P 500 constituents table from Wikipedia."""
    tables = pd.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        storage_options=UA_HEADERS,
    )
    # Confirmed table 0 has Symbol + GICS Sector + ~504 rows
    sp = tables[0][["Symbol", "GICS Sector"]].copy()
    sp.columns = ["ticker", "sector"]
    sp["ticker"] = sp["ticker"].astype(str).str.strip().str.upper()
    sp["sector"] = sp["sector"].map(lambda s: SECTOR_MAP.get(s, s))
    sp = sp[sp["ticker"].str.match(r"^[A-Z][A-Z\.\-]{0,5}$")]
    return sp.drop_duplicates(subset="ticker")


def fetch_unknown_tickers_from_motherduck() -> list[str]:
    """Pull every ticker that Congress traded in the last 90 days but isn't yet in dim_sectors."""
    import duckdb
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return []
    db = os.environ.get("MD_DATABASE", "stock_tracker")
    con = duckdb.connect(f"md:{db}?motherduck_token={token}")
    # Note: at this point dim_sectors has just been refreshed locally, but the
    # MotherDuck-side seed table only updates after `dbt seed`. Use the SQL we
    # have access to here, comparing against the in-memory S&P 500 list instead.
    rows = con.execute("""
        select distinct ticker
        from main_silver.silver_congress_trades
        where trade_date >= current_date - interval '90 days'
          and ticker is not null
          and ticker not in ('', '--', 'N/A')
    """).fetchall()
    con.close()
    return [r[0] for r in rows]


def yf_lookup_sector(ticker: str) -> str | None:
    """Resolve a ticker to a sector via yfinance .info; returns short label or None."""
    import yfinance as yf
    try:
        info = yf.Ticker(ticker.replace(".", "-")).info
        s = info.get("sector")
        if s:
            return YF_SECTOR_MAP.get(s, s)
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-other", action="store_true",
                    help="Look up sectors via yfinance for any ticker Congress traded "
                         "that isn't in S&P 500. Requires MOTHERDUCK_TOKEN.")
    args = ap.parse_args()

    print("Fetching S&P 500 from Wikipedia...")
    sp500 = fetch_sp500()
    print(f"  {len(sp500)} tickers w/ GICS sector")

    combined = sp500.copy()

    if args.backfill_other:
        if not os.environ.get("MOTHERDUCK_TOKEN"):
            sys.exit("--backfill-other needs MOTHERDUCK_TOKEN in env.")
        print("Pulling Congress-traded tickers from MotherDuck...")
        congress_tickers = set(fetch_unknown_tickers_from_motherduck())
        known = set(combined["ticker"])
        unknown = sorted(congress_tickers - known)
        print(f"  {len(unknown)} tickers traded by Congress but not on S&P 500")

        resolved = []
        for i, tk in enumerate(unknown, 1):
            sector = yf_lookup_sector(tk)
            if sector:
                resolved.append({"ticker": tk, "sector": sector})
                print(f"  [{i}/{len(unknown)}] {tk} → {sector}")
            else:
                print(f"  [{i}/{len(unknown)}] {tk} → (no sector available)")
            time.sleep(0.2)
        if resolved:
            combined = pd.concat([combined, pd.DataFrame(resolved)], ignore_index=True)
            combined = combined.drop_duplicates(subset="ticker", keep="first")

    combined = combined.sort_values("ticker")
    out = Path(__file__).resolve().parent.parent / "dbt" / "seeds" / "dim_sectors.csv"
    combined.to_csv(out, index=False)
    print(f"\nWrote {len(combined)} tickers → {out}")
    print("\nSector counts:")
    print(combined["sector"].value_counts().to_string())


if __name__ == "__main__":
    main()
