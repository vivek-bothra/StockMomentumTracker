import os
import json
import logging
import time

import pandas as pd
import yfinance as yf
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
DEBUG_YFINANCE = os.getenv("YF_DEBUG", "0").lower() in {"1", "true", "yes"}
if DEBUG_YFINANCE:
    yf.enable_debug_mode()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Google Sheets setup
SHEET_ID = '1wiVMF-bOePDKeaKpQx46FsjZ9pMn1C0RqpnxjNiajmw'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

service = None
try:
    if os.path.exists('credentials.json'):
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    elif os.getenv('GOOGLE_CREDENTIALS'):
        creds = Credentials.from_service_account_info(
            json.loads(os.getenv('GOOGLE_CREDENTIALS')), scopes=SCOPES
        )
    else:
        raise FileNotFoundError("Google credentials not provided")
    service = build('sheets', 'v4', credentials=creds)
except Exception as e:
    logging.warning(f"Google Sheets API disabled: {str(e)}")

# HTTP session configuration


def create_http_session():
    """Create an HTTP session for yfinance with an optional curl_cffi backend."""

    use_curl_cffi = os.getenv("USE_CURL_CFFI", "1").lower() not in {"0", "false", "no"}

    if use_curl_cffi:
        try:
            from curl_cffi import requests as curl_requests  # type: ignore

            session = curl_requests.Session(impersonate="chrome")
            logging.info("Using curl_cffi session for Yahoo Finance requests.")
            return session
        except Exception as exc:  # pragma: no cover - defensive fallback
            logging.warning(
                "curl_cffi session unavailable (%s); falling back to requests.",
                exc,
            )

    import requests

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )
    logging.info("Using requests session for Yahoo Finance requests.")
    return session


session = create_http_session()


def can_reach_yahoo_finance(session):
    """Check whether Yahoo Finance is reachable from the current runtime."""

    try:
        response = session.get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        response.raise_for_status()
        return True, ""
    except Exception as exc:
        return False, str(exc)

# Ticker list (single ticker for testing)
tickers = [
    "GOOGL", "META", "AMZN", "BABA", "0700.HK", "NFLX", "BIDU", "JD", "EBAY", "MELI",
    "SE", "4755.T", "ZAL.DE", "CPNG", "3690.HK", "PDD", "W", "SNAP", "PINS", "RDDT",
    "1024.HK", "035420.KS", "SPOT", "TME", "BILI", "ROKU", "HUYA", "IQ", "BKNG", "EXPE",
    "TCOM", "ABNB", "MMYT", "TRVG", "DESP", "PYPL", "XYZ", "ADYEN.AS", "NU", "COIN",
    "HOOD", "SOFI", "ETERNAL.NS", "DASH", "DHER.DE", "TKWY.AS", "UBER", "LYFT", "GRAB",
    "PRX.AS", "ZG", "REA.AX", "RMV.L", "CARG", "AUTO.L", "3659.T", "036570.KS", "TTWO",
    "EA", "RBLX", "U", "259960.KS", "DBX", "ZM", "TWLO", "SHOP", "GDDY", "WIX", "NET",
    "AKAM", "UPWK", "FVRR", "TDOC", "MTCH", "BMBL", "ANGI", "SSTK", "TTD", "VMEO",
    "4385.T", "JMIA", "ALE.WA", "ASC.L", "BOO.L", "CHWY", "ETSY", "HFG.DE", "JUSTDIAL.NS",
    "NAUKRI.NS", "069080.KS", "NTES", "NVDA", "035720.KS", "GRPN", "YELP", "TRIP",
    "SWIGGY.NS", "NYKAA.NS", "PAYTM.NS", "POLICYBZR.NS"
]

# Function to calculate EMA
def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

def fetch_stock_history(ticker, session, max_attempts=3):
    """Fetch ticker history with bounded retries."""

    retryable_markers = [
        "Read timed out",
        "Too Many Requests",
        "Rate limited",
        "temporarily unavailable",
        "Connection reset",
    ]

    for attempt in range(1, max_attempts + 1):
        try:
            stock = yf.Ticker(ticker, session=session)
            return stock.history(period="2y", auto_adjust=True)
        except Exception as exc:
            err_text = str(exc)
            is_retryable = any(marker.lower() in err_text.lower() for marker in retryable_markers)
            if not is_retryable or attempt == max_attempts:
                raise
            wait_seconds = min(2 ** attempt, 10)
            logging.warning(
                "Retryable fetch error for %s (attempt %s/%s): %s. Retrying in %ss.",
                ticker,
                attempt,
                max_attempts,
                err_text,
                wait_seconds,
            )
            time.sleep(wait_seconds)

# Fetch and calculate MACD for a ticker
def get_stock_data(ticker, session):
    try:
        logging.info(f"Fetching data for {ticker}")
        # Fetch history directly without info check
        df = fetch_stock_history(ticker, session)
        if df.empty:
            logging.warning(f"No data for {ticker}")
            return [ticker, "No Data", 0, 0, 0, 0, 0]
        
        # Resample to weekly (Friday close)
        weekly = df['Close'].resample('W-FRI').last().dropna()
        if len(weekly) < 26:  # Need at least 26 weeks for EMA26
            logging.warning(f"Insufficient data for {ticker}: {len(weekly)} weeks")
            return [ticker, round(weekly.iloc[-1], 2) if not weekly.empty else "No Data", 0, 0, 0, 0, 0]
        
        # Calculate MACD
        ema12 = calculate_ema(weekly, 12)
        ema26 = calculate_ema(weekly, 26)
        macd = ema12 - ema26
        signal = calculate_ema(macd, 9)
        hist = macd - signal
        
        return [
            ticker,
            round(weekly.iloc[-1], 2),
            round(ema12.iloc[-1], 2),
            round(ema26.iloc[-1], 2),
            round(macd.iloc[-1], 2),
            round(signal.iloc[-1], 2),
            round(hist.iloc[-1], 2)
        ]
    except Exception as e:
        logging.error(f"Error for {ticker}: {str(e)}")
        return [ticker, f"Error: {str(e)}", 0, 0, 0, 0, 0]
    finally:
        time.sleep(2)  # Modest delay to avoid rate limiting

# Fetch data for all tickers
results = []
reachable, connectivity_error = can_reach_yahoo_finance(session)

if not reachable:
    logging.error(
        "Yahoo Finance is unreachable from this environment. "
        "Skipping ticker fetches to avoid a long failing run. Error: %s",
        connectivity_error,
    )
    results = [[ticker, f"Fetch Error: {connectivity_error}", 0, 0, 0, 0, 0] for ticker in tickers]
else:
    for ticker in tickers:
        result = get_stock_data(ticker, session)
        results.append(result)
        logging.info(f"Processed {ticker}: {result[1]}")

# Add timestamp column
timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
results = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], timestamp] for r in results]

# Prepare data for Google Sheets
header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist", "Last Updated"]
body = [header] + results

# ----- Docs and trade log generation -----
df = pd.DataFrame(results, columns=header)
df["Momentum"] = (df["MACD"] > df["Signal"]).map({True: "Yes", False: "No"})

docs_dir = "docs"
os.makedirs(docs_dir, exist_ok=True)

# Append to history
history_path = os.path.join(docs_dir, "history.csv")
if os.path.exists(history_path):
    df.to_csv(history_path, mode="a", header=False, index=False)
else:
    df.to_csv(history_path, index=False)

# Build trade log based on momentum changes
last_state_path = os.path.join(docs_dir, "last_momentum.json")
if os.path.exists(last_state_path):
    with open(last_state_path, "r") as f:
        last_state = json.load(f)
else:
    last_state = {}

# Track open positions to compute profits on SELL
positions_path = os.path.join(docs_dir, "positions.json")
if os.path.exists(positions_path):
    with open(positions_path, "r") as f:
        positions = json.load(f)
else:
    positions = {}

trades = []
for _, row in df.iterrows():
    ticker = row["Ticker"]
    momentum = row["Momentum"]
    price = row["Weekly Close"]
    prev = last_state.get(ticker)

    try:
        numeric_price = float(price)
    except (TypeError, ValueError):
        # Keep momentum state in sync even when data fetch failed.
        last_state[ticker] = momentum
        continue

    if momentum == "Yes" and prev != "Yes":
        trades.append([ticker, "BUY", numeric_price, timestamp, ""])
        positions[ticker] = numeric_price
    elif momentum == "No" and prev == "Yes":
        buy_price = positions.pop(ticker, numeric_price)
        profit = round(numeric_price - float(buy_price), 2)
        trades.append([ticker, "SELL", numeric_price, timestamp, profit])
    last_state[ticker] = momentum

trade_log_path = os.path.join(docs_dir, "trade_log.csv")
if trades:
    trade_df = pd.DataFrame(trades, columns=["Ticker", "Action", "Price", "Timestamp", "Profit"])
    if os.path.exists(trade_log_path):
        trade_df.to_csv(trade_log_path, mode="a", header=False, index=False)
    else:
        trade_df.to_csv(trade_log_path, index=False)

with open(last_state_path, "w") as f:
    json.dump(last_state, f)
with open(positions_path, "w") as f:
    json.dump(positions, f)

# Generate simple HTML page
trade_log_df = (
    pd.read_csv(trade_log_path)
    if os.path.exists(trade_log_path)
    else pd.DataFrame(columns=["Ticker", "Action", "Price", "Timestamp", "Profit"])
)
if "Profit" not in trade_log_df.columns:
    trade_log_df["Profit"] = ""

# Build responsive HTML using Bootstrap
html_content = f"""
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Stock Momentum Tracker</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="container my-4">
    <h1 class="mb-4">Latest Momentum</h1>
    <div class="table-responsive">
        {df.to_html(index=False, classes='table table-striped')}
    </div>
    <h1 class="mt-5">Trade Log</h1>
    <div class="table-responsive">
        {trade_log_df.to_html(index=False, classes='table table-striped')}
    </div>
</body>
</html>
"""
with open(os.path.join(docs_dir, "index.html"), "w", encoding="utf-8") as f:
    f.write(html_content)
# ----- End docs section -----

# Update Google Sheet with retry logic
if service:
    sheet = service.spreadsheets()
    clear_range = "Sheet1!A1:H1000"  # Clear a large range
    range_name = f"Sheet1!A1:H{len(results) + 1}"
    max_attempts = 5

    for attempt in range(1, max_attempts + 1):
        try:
            logging.info(f"Clearing Google Sheet at range {clear_range}")
            sheet.values().clear(spreadsheetId=SHEET_ID, range=clear_range).execute()
            logging.info(f"Attempting to update Google Sheet at range {range_name}")
            request = sheet.values().update(
                spreadsheetId=SHEET_ID,
                range=range_name,
                valueInputOption="RAW",
                body={"values": body}
            ).execute()
            logging.info(
                f"Successfully updated Google Sheet with {len(results)} tickers: {request.get('updatedCells')} cells updated"
            )
            break
        except (TimeoutError, HttpError) as e:
            logging.warning(f"Attempt {attempt} failed: {str(e)}")
            if attempt == max_attempts:
                logging.error("Exceeded maximum attempts to update Google Sheet")
                raise
            time.sleep(2 ** attempt)
        except Exception as e:
            logging.error(f"Unexpected error updating Google Sheet: {str(e)}")
            raise

    print(f"Updated Google Sheet with {len(results)} tickers.")
else:
    logging.info("Google Sheets service not initialized; skipping Sheet update.")
