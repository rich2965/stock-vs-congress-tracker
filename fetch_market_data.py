"""
fetch_market_data.py
Extracts hourly OHLCV (yfinance) + Congressional trades (House + Senate Stock Watcher S3)
and lands raw JSON into MotherDuck bronze tables (append-only).
"""
import os, json, sys, time
from datetime import datetime, timezone
import requests
import yfinance as yf
import duckdb

# ---- Config ----
MD_TOKEN = os.environ["MOTHERDUCK_TOKEN"]
DB_NAME  = os.environ.get("MD_DATABASE", "stock_tracker")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

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

def yf_symbol(s): return s.replace(".", "-")

HSW_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SSW_URL = "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json"

RUN_TS = datetime.now(timezone.utc).isoformat()

# ---- HTTP session for S3 fetches only ----
# (yfinance >= 0.2.55 manages its own curl_cffi session and rejects requests.Session.)
session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "*/*"})

# ---- MotherDuck ----
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

# ---- 1. Stocks via yfinance ----
# Strategy: per-ticker fetch with a UA-bearing session, small jitter between calls.
# (Batch download has been flaky in recent yfinance versions; per-ticker is slower
# but far more reliable in CI.)
print(f"Fetching {len(TICKERS)} tickers from yfinance...")

failed = []
ok = 0
for i, orig in enumerate(TICKERS, 1):
    yfs = yf_symbol(orig)
    try:
        t = yf.Ticker(yfs)   # let yfinance use its own curl_cffi session
        hist = t.history(period="1mo", interval="1h", auto_adjust=False, raise_errors=False)
        if hist is None or hist.empty:
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
            for idx, row in hist.iterrows()
        ]
        payload = {"symbol": orig, "interval": "1h", "bars": bars}
        con.execute(
            "INSERT INTO bronze.raw_stock_prices VALUES (?, ?, ?);",
            [orig, RUN_TS, json.dumps(payload)],
        )
        ok += 1
        if i % 10 == 0:
            print(f"  {i}/{len(TICKERS)} done ({ok} ok, {len(failed)} failed)")
    except Exception as e:
        failed.append((orig, str(e)))
        print(f"  {orig} FAILED: {e}", file=sys.stderr)
    time.sleep(0.3)  # be polite, avoid Yahoo throttling

print(f"stocks: {ok}/{len(TICKERS)} ok, {len(failed)} failed")

# ---- 2. Congressional trades: House + Senate Stock Watcher ----
for source, url in (("house", HSW_URL), ("senate", SSW_URL)):
    try:
        r = session.get(url, timeout=120)
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
    print(f"\nFailed tickers ({len(failed)}):")
    for f in failed[:20]:
        print(f"  {f}")
