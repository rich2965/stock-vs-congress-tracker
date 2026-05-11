"""
fetch_market_data.py
Extracts hourly OHLCV (yfinance) + Congressional trades (House + Senate Stock Watcher S3)
and lands raw JSON into MotherDuck bronze tables (append-only).
"""
import os, json, sys
from datetime import datetime, timezone
import requests
import yfinance as yf
import duckdb

# ---- Config ----
MD_TOKEN = os.environ["MOTHERDUCK_TOKEN"]
DB_NAME  = os.environ.get("MD_DATABASE", "stock_tracker")

TICKERS = [
    "NVDA","AAPL","MSFT","AVGO","CRM","ORCL","ADBE","AMD","CSCO","INTC",
    "JPM","BRK.B","V","MA","BAC","WFC","GS","MS","C","BLK",
    "LLY","JNJ","UNH","ABBV","MRK","TMO","AMGN","PFE","ABT","DHR",
    "AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","BKNG","TJX","CMG",
    "GOOGL","META","NFLX","DIS","TMUS","VZ","CMCSA","T","WBD","CHTR",
    "CAT","GE","RTX","UNP","HON","LMT","UPS","DE","BA","FDX",
    "WMT","COST","PG","KO","PEP","PM","MDLZ","MO","TGT","CL",
    "XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","OXY","HAL",
    "NEE","DUK","SO","CEG","D","AEP","SRE","PCG","EXC","VST",
    "PLD","AMT","EQIX","WELL","SPG","CCI","PSA","O","DRE","CSGP",
    "LIN","FCX","SHW","APD","ECL","NEM","DOW","NUE","CTVA","VMC",
]

# yfinance uses "-" instead of "." for share classes (BRK.B -> BRK-B)
def yf_symbol(s): return s.replace(".", "-")

HSW_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SSW_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

RUN_TS = datetime.now(timezone.utc).isoformat()

# ---- Connect ----
con = duckdb.connect(f"md:{DB_NAME}?motherduck_token={MD_TOKEN}")
con.execute("CREATE SCHEMA IF NOT EXISTS bronze;")
con.execute("""
    CREATE TABLE IF NOT EXISTS bronze.raw_stock_prices (
        symbol VARCHAR,
        extracted_at TIMESTAMPTZ,
        payload JSON
    );
""")
con.execute("""
    CREATE TABLE IF NOT EXISTS bronze.raw_congress_trades (
        source VARCHAR,
        extracted_at TIMESTAMPTZ,
        payload JSON
    );
""")

# ---- 1. Stocks via yfinance (one batched download, no rate limit headaches) ----
yf_tickers = [yf_symbol(t) for t in TICKERS]
print(f"Fetching {len(yf_tickers)} tickers from yfinance...")

df = yf.download(
    tickers=yf_tickers,
    period="1mo",
    interval="1h",
    group_by="ticker",
    auto_adjust=False,
    threads=True,
    progress=False,
)

failed = []
for orig, yfs in zip(TICKERS, yf_tickers):
    try:
        # When multiple tickers requested, df has a multi-index column [ticker, field]
        sub = df[yfs].dropna(how="all") if yfs in df.columns.get_level_values(0) else None
        if sub is None or sub.empty:
            failed.append(orig); continue

        bars = [
            {
                "ts": idx.isoformat(),
                "open":   None if (v := row["Open"])   != v else float(v),
                "high":   None if (v := row["High"])   != v else float(v),
                "low":    None if (v := row["Low"])    != v else float(v),
                "close":  None if (v := row["Close"])  != v else float(v),
                "volume": None if (v := row["Volume"]) != v else int(v),
            }
            for idx, row in sub.iterrows()
        ]
        payload = {"symbol": orig, "interval": "1h", "bars": bars}
        con.execute(
            "INSERT INTO bronze.raw_stock_prices VALUES (?, ?, ?);",
            [orig, RUN_TS, json.dumps(payload)],
        )
    except Exception as e:
        failed.append((orig, str(e)))
        print(f"  {orig} FAILED: {e}", file=sys.stderr)

print(f"stocks: {len(TICKERS)-len(failed)}/{len(TICKERS)} ok")

# ---- 2. Congressional trades: House + Senate Stock Watcher ----
for source, url in (("house", HSW_URL), ("senate", SSW_URL)):
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        trades = r.json()
        con.execute(
            "INSERT INTO bronze.raw_congress_trades VALUES (?, ?, ?);",
            [source, RUN_TS, json.dumps(trades)],
        )
        print(f"{source}: {len(trades)} trades ok")
    except Exception as e:
        print(f"{source} FAILED: {e}", file=sys.stderr)

con.close()

if failed:
    print(f"\n{len(failed)} ticker(s) failed:")
    for f in failed:
        print(f"  {f}")
