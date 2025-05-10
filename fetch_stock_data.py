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

# Ticker list
tickers = [
    "GOOGL", "META", "AMZN", "BABA", "0700.HK", "NFLX", "BIDU", "JD", "EBAY", "MELI",
    "SE", "4755.T", "ZAL.DE", "CPNG", "3690.HK", "PDD", "W",......................................................................................., "NYKAA.NS", "PAYTM.NS", "POLICYBZR.NS"
]

# Function to calculate EMA
def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

# Function to get Yahoo Finance cookie and crumb
def get_yahoo_credentials():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # Get cookie
        response = requests.get('https://fc.yahoo.com', headers=headers)
        if response.status_code != 404:
            logging.error(f"Failed to get cookie: {response.status_code}")
            return None, None
        cookie = response.headers.get('set-cookie')
        if not cookie:
            logging.error("No cookie received")
            return None, None
        
        # Get crumb
        crumb_url = 'https://query2.finance.yahoo.com/v1/test/getcrumb'
        response = requests.get(crumb_url, headers=headers, cookies={'A3': cookie.split(';')[0]})
        if response.status_code != 200:
            logging.error(f"Failed to get crumb: {response.status_code}")
            return None, None
        crumb = response.text.strip()
        return cookie, crumb
    except Exception as e:
        logging.error(f"Error getting Yahoo credentials: {str(e)}")
        return None, None

# Retry decorator for handling temporary API failures
@retry(stop_max_attempt_number=3, wait_fixed=2000)
def fetch_stock_history(ticker, cookie, crumb):
    stock = yf.Ticker(ticker)
    return stock.history(period="2y", auto_adjust=True, headers={'User-Agent': 'Mozilla/5.0', 'Cookie': cookie, 'Crumb': crumb})

# Fetch and calculate MACD for a ticker
def get_stock_data(ticker):
    try:
        logging.info(f"Fetching data for {ticker}")
        # Get Yahoo credentials
        cookie, crumb = get_yahoo_credentials()
        if not cookie or not crumb:
            logging.warning(f"Failed to get Yahoo credentials for {ticker}")
            return [ticker, "Auth Error", 0, 0, 0, 0, 0]
        
        # Validate ticker
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or 'symbol' not in info:
            logging.warning(f"Invalid or unsupported ticker: {ticker}")
            return [ticker, "Invalid Ticker", 0, 0, 0, 0, 0]
        
        # Fetch history with retry
        df = fetch_stock_history(ticker, cookie, crumb)
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
        time.sleep(1)  # Delay to avoid rate limiting

# Fetch data for all tickers
results = []
for ticker in tickers:
    result = get_stock_data(ticker)
    results.append(result)
    logging.info(f"Processed {ticker}: {result[1]}")

# Add timestamp column
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
results = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], timestamp] for r in results]

# Prepare data for Google Sheets
header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist", "Last Updated"]
body = [header] + results

# Update Google Sheet
try:
    sheet = service.spreadsheets()
    range_name = f"Sheet1!A1:H{len(results) + 1}"  # Dynamic range
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
