"""
fetch_market_data.py
Extracts hourly OHLCV (Alpha Vantage) + Congressional trades (Quiver Quant)
and lands raw JSON into MotherDuck bronze tables (append-only).
"""
import os, json, time, sys
from datetime import datetime, timezone
import requests
import duckdb

# ---- Config ----
AV_KEY   = os.environ["ALPHAVANTAGE_API_KEY"]
QQ_KEY   = os.environ["QUIVER_API_KEY"]
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

RUN_TS = datetime.now(timezone.utc).isoformat()

# ---- Helpers ----
def get_av_hourly(symbol: str) -> dict:
    """Alpha Vantage TIME_SERIES_INTRADAY 60min."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": "60min",
        "outputsize": "compact",   # last ~100 bars; keeps payload small
        "apikey": AV_KEY,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def get_qq_congress() -> list:
    """Quiver Quant: recent congressional trades (all members)."""
    url = "https://api.quiverquant.com/beta/live/congresstrading"
    r = requests.get(url, headers={"Authorization": f"Bearer {QQ_KEY}"}, timeout=60)
    r.raise_for_status()
    return r.json()

# ---- Connect to MotherDuck ----
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
        extracted_at TIMESTAMPTZ,
        payload JSON
    );
""")

# ---- Stocks: Alpha Vantage free tier ~5 req/min, 500/day ----
# Loop tickers, respect rate limit, append-only.
failed = []
for i, sym in enumerate(TICKERS, 1):
    try:
        data = get_av_hourly(sym)
        # Skip throttled/empty responses but still log
        if "Time Series (60min)" not in data:
            failed.append((sym, data.get("Note") or data.get("Information") or "no_data"))
        con.execute(
            "INSERT INTO bronze.raw_stock_prices VALUES (?, ?, ?);",
            [sym, RUN_TS, json.dumps(data)],
        )
        print(f"[{i}/{len(TICKERS)}] {sym} ok")
    except Exception as e:
        failed.append((sym, str(e)))
        print(f"[{i}/{len(TICKERS)}] {sym} FAILED: {e}", file=sys.stderr)
    time.sleep(13)   # ~5 req/min ceiling for free tier; tune if premium

# ---- Congressional trades ----
try:
    trades = get_qq_congress()
    con.execute(
        "INSERT INTO bronze.raw_congress_trades VALUES (?, ?);",
        [RUN_TS, json.dumps(trades)],
    )
    print(f"congress trades ok ({len(trades)} rows)")
except Exception as e:
    print(f"congress trades FAILED: {e}", file=sys.stderr)

con.close()

if failed:
    print(f"\n{len(failed)} ticker(s) failed/throttled:")
    for s, msg in failed:
        print(f"  {s}: {msg}")
