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
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)  # <-- suppress file_cache warning
except Exception as e:
    logging.error(f"Failed to initialize Google Sheets API: {str(e)}")
    raise

# Ticker list
tickers = ["GOOGL", "META", "AMZN", "NFLX", "PYPL", "UBER", "SHOP", "ZOMATO.NS", "PAYTM.NS", "NYKAA.NS"]

def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

@retry(stop_max_attempt_number=3, wait_exponential_multiplier=3000, wait_exponential_max=30000)
def fetch_stock_history(ticker, session):
    stock = yf.Ticker(ticker, session=session)
    return stock.history(period="2y", auto_adjust=True)

def get_stock_data(ticker, session):
    try:
        logging.info(f"Fetching data for {ticker}")
        
        # Fetch history with retry
        df = fetch_stock_history(ticker, session)
        if df.empty:
            logging.warning(f"No data for {ticker}")
            return [ticker, "No Data", 0, 0, 0, 0, 0]
        
        # Resample to weekly (Friday close)
        weekly = df['Close'].resample('W-FRI').last().dropna()
        if len(weekly) < 26:
            logging.warning(f"Insufficient data for {ticker}: {len(weekly)} weeks")
            return [ticker, round(weekly.iloc[-1], 2) if not weekly.empty else "No Data", 0, 0, 0, 0, 0]
        
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
        time.sleep(15)  # Throttle calls to avoid rate limiting

results = []
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'})
failed_tickers = []

for ticker in tickers:
    result = get_stock_data(ticker, session)
    results.append(result)
    logging.info(f"Processed {ticker}: {result[1]}")
    if "Rate limited" in str(result[1]):
        failed_tickers.append(ticker)

if failed_tickers:
    logging.info(f"Retrying {len(failed_tickers)} failed tickers after 60-second delay")
    time.sleep(60)
    for ticker in failed_tickers:
        result = get_stock_data(ticker, session)
        for i, r in enumerate(results):
            if r[0] == ticker:
                results[i] = result
                break
        logging.info(f"Retry processed {ticker}: {result[1]}")

timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
results = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], timestamp] for r in results]

header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist", "Last Updated"]
body = [header] + results

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
