import yfinance as yf
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import logging
import time
import requests
from retrying import retry

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

# Ticker list (complete list of 100 tickers)
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

# Retry decorator for handling temporary API failures
@retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_stock_history(ticker):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'})
    stock = yf.Ticker(ticker, session=session)
    return stock.history(period="2y", auto_adjust=True)

# Fetch and calculate MACD for a ticker
def get_stock_data(ticker):
    try:
        logging.info(f"Fetching data for {ticker}")
        # Validate ticker
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'})
        stock = yf.Ticker(ticker, session=session)
        info = stock.info
        if not info or 'symbol' not in info:
            logging.warning(f"Invalid or unsupported ticker: {ticker}")
            return [ticker, "Invalid Ticker", 0, 0, 0, 0, 0]
        
        # Fetch history with retry
        df = fetch_stock_history(ticker)
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
        time.sleep(1.5)  # Delay to avoid rate limiting

# Fetch data for all tickers
results = []
for ticker in tickers:
    result = get_stock_data(ticker)
    results.append(result)
    logging.info(f"Processed {ticker}: {result[1]}")

# Add timestamp column
timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
results = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], timestamp] for r in results]

# Prepare data for Google Sheets
header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist", "Last Updated"]
body = [header] + results

# Update Google Sheet
try:
    sheet = service.spreadsheets()
    range_name = f"Sheet1!A1:H{len(results) + 1}"
    request = sheet.values().update(
        spreadsheetId=SHEET_ID,
        range=range_name,
        valueInputOption="RAW",
        body={"values": body}
    ).execute()
    logging.info(f"Updated Google Sheet with {len(results)} tickers.")
except Exception as e:
    logging.error(f"Failed to update Google Sheet: {str(e)}")
    raise

print(f"Updated Google Sheet with {len(results)} tickers.")
