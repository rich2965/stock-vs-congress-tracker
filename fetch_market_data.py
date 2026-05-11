"""
fetch_market_data.py
Extracts hourly OHLCV (yfinance) + Congressional trades (Capitol Trades JSON API)
and lands raw JSON into MotherDuck bronze tables (append-only).
"""
import os, json, sys, time
from datetime import datetime, timezone, timedelta
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

CT_URL = "https://bff.capitoltrades.com/trades"
RUN_TS = datetime.now(timezone.utc).isoformat()

# ---- HTTP session for Capitol Trades (yfinance manages its own) ----
session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "application/json",
    "Origin": "https://www.capitoltrades.com",
    "Referer": "https://www.capitoltrades.com/",
})

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
print(f"Fetching {len(TICKERS)} tickers from yfinance...")
failed, ok = [], 0
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
    time.sleep(0.3)

print(f"stocks: {ok}/{len(TICKERS)} ok, {len(failed)} failed")

# ---- 2. Congressional trades via Capitol Trades backend API ----
# Paginate from most-recent backwards; stop after we've covered ~45 days of trades.
# pageSize=96 is what their UI uses; date strings are ISO so lexicographic compare is safe.
def fetch_capitoltrades(days_back=45, max_pages=60):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
    out = []
    for page in range(1, max_pages + 1):
        r = session.get(
            CT_URL,
            params={"page": page, "pageSize": 96, "sortBy": "-pubDate"},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        trades = body.get("data", [])
        if not trades:
            break
        out.extend(trades)

        # Stop once the page's youngest trade is older than the cutoff
        dates = [t.get("txDate") or t.get("filingDate") for t in trades]
        dates = [d for d in dates if d]
        if dates and max(dates) < cutoff:
            break
        time.sleep(0.4)
    return out

try:
    trades = fetch_capitoltrades()
    # Log one example record so we can verify the shape in the run log
    if trades:
        print("sample trade keys:", sorted(trades[0].keys()))
    con.execute(
        "INSERT INTO bronze.raw_congress_trades VALUES (?, ?, ?);",
        ["capitoltrades", RUN_TS, json.dumps(trades)],
    )
    print(f"capitoltrades: {len(trades)} trades ok")
except Exception as e:
    print(f"capitoltrades FAILED: {e}", file=sys.stderr)

con.close()

if failed:
    print(f"\nFailed tickers ({len(failed)}):")
    for f in failed[:20]:
        print(f"  {f}")
