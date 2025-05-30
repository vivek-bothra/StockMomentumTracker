import yfinance as yf
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging
import time
from curl_cffi import requests
from retrying import retry

# Enable yfinance debug mode
yf.enable_debug_mode()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Google Sheets setup
SHEET_ID = '1wiVMF-bOePDKeaKpQx46FsjZ9pMn1C0RqpnxjNiajmw'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

try:
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
except Exception as e:
    logging.error(f"Failed to initialize Google Sheets API: {str(e)}")
    raise

# Ticker list (single ticker for testing)
tickers = [
    "GOOGL", "META", "AMZN", "BABA", "0700.HK", "NFLX", "BIDU", "JD", "EBAY", "MELI",
    "SE", "4755.T", "ZAL.DE", "CPNG", "3690.HK", "PDD", "W", "SNAP", "PINS", "RDDT",
    "1024.HK", "035420.KS", "SPOT", "TME", "BILI", "ROKU", "HUYA", "IQ", "BKNG", "EXPE",
    "TCOM", "ABNB", "MMYT", "TRVG", "DESP", "PYPL", "SQ", "ADYEN.AS", "NU", "COIN",
    "HOOD", "SOFI", "ZOMATO.NS", "DASH", "DHER.DE", "TKWY.AS", "UBER", "LYFT", "GRAB",
    "PRX.AS", "ZG", "REA.AX", "RMV.L", "CARG", "AUTO.L", "3659.T", "036570.KS", "TTWO",
    "EA", "RBLX", "U", "259960.KS", "DBX", "ZM", "TWLO", "SHOP", "GDDY", "WIX", "NET",
    "AKAM", "UPWK", "FVRR", "TDOC", "MTCH", "BMBL", "ANGI", "SSTK", "TTD", "VMEO",
    "4385.T", "JMIA", "ALE.WA", "ASC.L", "BOO.L", "CHWY", "ETSY", "HFG.DE", "JUSTDIAL.NS",
    "NAUKRI.NS", "069080.KS", "NTES", "YY", "035720.KS", "GRPN", "YELP", "TRIP",
    "SWIGGY.NS", "NYKAA.NS", "PAYTM.NS", "POLICYBZR.NS"
]

# Function to calculate EMA
def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

# Retry decorator with exponential backoff
@retry(stop_max_attempt_number=5, wait_exponential_multiplier=1000, wait_exponential_max=15000)
def fetch_stock_history(ticker, session):
    stock = yf.Ticker(ticker, session=session)
    return stock.history(period="2y", auto_adjust=True)

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

# Fetch data for all tickers with retry for rate-limited tickers
results = []
session = requests.Session(impersonate="chrome")  # Use curl_cffi with Chrome TLS fingerprint
failed_tickers = []

for ticker in tickers:
    result = get_stock_data(ticker, session)
    results.append(result)
    logging.info(f"Processed {ticker}: {result[1]}")
    if "Rate limited" in str(result[1]):
        failed_tickers.append(ticker)

# Retry failed tickers after a longer delay
if failed_tickers:
    logging.info(f"Retrying {len(failed_tickers)} failed tickers after 120-second delay")
    time.sleep(120)
    for ticker in failed_tickers:
        result = get_stock_data(ticker, session)
        # Update result in results list
        for i, r in enumerate(results):
            if r[0] == ticker:
                results[i] = result
                break
        logging.info(f"Retry processed {ticker}: {result[1]}")

# Add timestamp column
timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
results = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], timestamp] for r in results]

# Prepare data for Google Sheets
header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist", "Last Updated"]
body = [header] + results

# Clear existing data in the Sheet range
try:
    sheet = service.spreadsheets()
    clear_range = "Sheet1!A1:H1000"  # Clear a large range
    logging.info(f"Clearing Google Sheet at range {clear_range}")
    sheet.values().clear(spreadsheetId=SHEET_ID, range=clear_range).execute()
except HttpError as e:
    logging.error(f"Failed to clear Google Sheet: {str(e)}")
    raise
except Exception as e:
    logging.error(f"Unexpected error clearing Google Sheet: {str(e)}")
    raise

# Update Google Sheet
try:
    range_name = f"Sheet1!A1:H{len(results) + 1}"
    logging.info(f"Attempting to update Google Sheet at range {range_name}")
    request = sheet.values().update(
        spreadsheetId=SHEET_ID,
        range=range_name,
        valueInputOption="RAW",
        body={"values": body}
    ).execute()
    logging.info(f"Successfully updated Google Sheet with {len(results)} tickers: {request.get('updatedCells')} cells updated")
except HttpError as e:
    logging.error(f"Google Sheets API error: {str(e)}")
    raise
except Exception as e:
    logging.error(f"Unexpected error updating Google Sheet: {str(e)}")
    raise

print(f"Updated Google Sheet with {len(results)} tickers.")
