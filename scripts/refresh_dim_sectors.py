"""
Build dbt/seeds/dim_sectors.csv from public sources.

Layered approach:
  1) S&P 500 from Wikipedia        — ~503 tickers w/ official GICS Sector and
                                     company name (always)
  2) yfinance for "Other" tickers  — looks up sector + company name for any
                                     ticker Congress has actually traded that
                                     isn't on the S&P 500 list (optional;
                                     requires MotherDuck creds)

Output schema: ticker, company_name, sector

Usage:
    pip install pandas lxml yfinance duckdb
    python scripts/refresh_dim_sectors.py
    MOTHERDUCK_TOKEN=... python scripts/refresh_dim_sectors.py --backfill-other
    # then commit dbt/seeds/dim_sectors.csv
"""
import argparse, os, sys, time
from pathlib import Path
import pandas as pd

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
YF_SECTOR_MAP = dict(SECTOR_MAP)
UA_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dim-sectors-refresh)"}


def fetch_sp500() -> pd.DataFrame:
    tables = pd.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        storage_options=UA_HEADERS,
    )
    sp = tables[0][["Symbol", "Security", "GICS Sector"]].copy()
    sp.columns = ["ticker", "company_name", "sector"]
    sp["ticker"] = sp["ticker"].astype(str).str.strip().str.upper()
    # Strip commas from names so CSV is well-formed without quoting
    sp["company_name"] = sp["company_name"].astype(str).str.strip().str.replace(",", " ", regex=False)
    sp["sector"] = sp["sector"].map(lambda s: SECTOR_MAP.get(s, s))
    sp = sp[sp["ticker"].str.match(r"^[A-Z][A-Z\.\-]{0,5}$")]
    return sp.drop_duplicates(subset="ticker")


def fetch_unknown_tickers_from_motherduck() -> list[str]:
    import duckdb
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        return []
    db = os.environ.get("MD_DATABASE", "stock_tracker")
    con = duckdb.connect(f"md:{db}?motherduck_token={token}")
    rows = con.execute("""
        select distinct ticker
        from main_silver.silver_congress_trades
        where trade_date >= current_date - interval '90 days'
          and ticker is not null
          and ticker not in ('', '--', 'N/A')
    """).fetchall()
    con.close()
    return [r[0] for r in rows]


def yf_lookup(ticker: str) -> dict | None:
    import yfinance as yf
    try:
        info = yf.Ticker(ticker.replace(".", "-")).info
        sector = info.get("sector")
        name = info.get("longName") or info.get("shortName")
        if sector or name:
            return {
                "ticker": ticker,
                "company_name": (name or "").replace(",", " "),
                "sector": YF_SECTOR_MAP.get(sector, sector) if sector else "Other",
            }
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-other", action="store_true")
    args = ap.parse_args()

    print("Fetching S&P 500 from Wikipedia...")
    sp500 = fetch_sp500()
    print(f"  {len(sp500)} tickers")
    combined = sp500.copy()

    if args.backfill_other:
        if not os.environ.get("MOTHERDUCK_TOKEN"):
            sys.exit("--backfill-other needs MOTHERDUCK_TOKEN")
        print("Pulling Congress-traded tickers from MotherDuck...")
        congress = set(fetch_unknown_tickers_from_motherduck())
        unknown = sorted(congress - set(combined["ticker"]))
        print(f"  {len(unknown)} tickers traded by Congress but not on S&P 500")
        resolved = []
        for i, tk in enumerate(unknown, 1):
            r = yf_lookup(tk)
            if r:
                resolved.append(r)
                print(f"  [{i}/{len(unknown)}] {tk} → {r['sector']} ({r['company_name']})")
            else:
                print(f"  [{i}/{len(unknown)}] {tk} → (skip)")
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
