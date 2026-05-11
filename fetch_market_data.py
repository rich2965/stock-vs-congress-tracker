"""
fetch_market_data.py
Extracts hourly OHLCV (yfinance) + Congressional trades (scraped from capitoltrades.com)
and lands raw JSON into MotherDuck bronze tables (append-only).
"""
import os, json, sys, time, re
from datetime import datetime, timezone, timedelta
import yfinance as yf
import duckdb
from playwright.sync_api import sync_playwright

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

RUN_TS = datetime.now(timezone.utc).isoformat()

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
        t = yf.Ticker(yfs)
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
        con.execute(
            "INSERT INTO bronze.raw_stock_prices VALUES (?, ?, ?);",
            [orig, RUN_TS, json.dumps({"symbol": orig, "interval": "1h", "bars": bars})],
        )
        ok += 1
        if i % 10 == 0:
            print(f"  {i}/{len(TICKERS)} done ({ok} ok, {len(failed)} failed)")
    except Exception as e:
        failed.append((orig, str(e)))
        print(f"  {orig} FAILED: {e}", file=sys.stderr)
    time.sleep(0.3)
print(f"stocks: {ok}/{len(TICKERS)} ok, {len(failed)} failed")

# ---- 2. Congressional trades scraped from capitoltrades.com ----
# We render the page with Playwright and extract each row from the rendered table.
# Columns observed on capitoltrades.com/trades (left → right):
#   0: Politician       (name + party + chamber as multiline text)
#   1: Traded Issuer    (company + ticker)
#   2: Published        ("16 Apr 2024" or "X days ago")
#   3: Traded           ("16 Apr 2024")
#   4: Filed after      ("3 days", "45 days", etc.)
#   5: Owner            ("Self", "Spouse", "Joint", "Child", "Undisclosed")
#   6: Type             ("buy", "sell", "exchange", "receive")
#   7: Size             ("1K–15K", "15K–50K", ..., "50M+")
#   8: Price            ("$NVDA 120.50" or "N/A")
#
# If Capitol Trades rearranges columns, this script will still capture *all* cell
# text into the bronze JSON — silver decides which positions to read.

def parse_traded_date(s: str):
    """'16 Apr 2024' -> ISO date string, else None."""
    if not s: return None
    try:
        return datetime.strptime(s.strip(), "%d %b %Y").date().isoformat()
    except Exception:
        return None

def scrape_capitoltrades(days_back=45, max_pages=60):
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=days_back)).date().isoformat()
    all_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        for pg in range(1, max_pages + 1):
            url = f"https://www.capitoltrades.com/trades?pageSize=96&page={pg}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_selector("table tbody tr", timeout=25000)
            except Exception as e:
                print(f"  page {pg} load failed: {e}", file=sys.stderr)
                break

            rows = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('table tbody tr')).map(tr => {
                    const cells = Array.from(tr.querySelectorAll('td'));
                    // Per cell: split innerText by newlines so multiline labels are preserved
                    const text = cells.map(td => td.innerText.split('\\n').map(s => s.trim()).filter(Boolean));
                    // Also pull any ticker links (Issuer cell usually has an <a href="/stocks/XYZ">)
                    const tickerEl = tr.querySelector('a[href^="/stocks/"]');
                    const ticker = tickerEl ? tickerEl.getAttribute('href').split('/').pop() : null;
                    return { text, ticker };
                });
            }""")
            if not rows:
                break
            all_rows.extend(rows)

            # Stop once the most recent "Traded" date on this page is older than cutoff
            # text[3][0] is the Traded date string
            page_dates = []
            for r in rows:
                try:
                    d = parse_traded_date(r["text"][3][0])
                    if d: page_dates.append(d)
                except Exception:
                    pass
            if page_dates and max(page_dates) < cutoff_iso:
                print(f"  stopped at page {pg}: all trades older than {cutoff_iso}")
                break
            time.sleep(0.4)
        browser.close()
    return all_rows

try:
    trades = scrape_capitoltrades()
    if trades:
        print("sample row:", json.dumps(trades[0])[:500])
    con.execute(
        "INSERT INTO bronze.raw_congress_trades VALUES (?, ?, ?);",
        ["capitoltrades", RUN_TS, json.dumps(trades)],
    )
    print(f"capitoltrades: {len(trades)} rows scraped")
except Exception as e:
    print(f"capitoltrades FAILED: {e}", file=sys.stderr)

con.close()

if failed:
    print(f"\nFailed tickers ({len(failed)}):")
    for f in failed[:20]:
        print(f"  {f}")
