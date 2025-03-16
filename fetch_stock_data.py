import yfinance as yf
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Google Sheets setup
SHEET_ID = '1wiVMF-bOePDKeaKpQx46FsjZ9pMn1C0RqpnxjNiajmw'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)

# Ticker list with 100 unique entries (replaced ADE.OL, SQSP, DCT, YNDX with SWIGGY.NS, NYKAA.NS, PAYTM.NS, POLICYBZR.NS)
tickers = [
    "GOOGL", "META", "AMZN", "BABA", "0700.HK", "NFLX", "BIDU", "JD", "EBAY", "MELI",
    "SE", "4755.T", "ZAL.DE", "CPNG", "3690.HK", "PDD", "W", "SNAP", "PINS", "RDDT",
    "1024.HK", "035420.KS", "SPOT", "TME", "BILI", "ROKU", "HUYA", "IQ", "BKNG", "EXPE",
    "TCOM", "ABNB", "MMYT", "TRVG", "DESP", "PYPL", "SQ", "ADYEN.AS", "NU", "COIN",
    "HOOD", "SOFI", "ZOMATO.NS", "DASH", "DHER.DE", "TKWY.AS", "UBER", "LYFT", "GRAB",
    "PRX.AS", "ZG", "REA.AX", "RMV.L", "CARG", "AUTO.L", "3659.T",
    "036570.KS", "TTWO", "EA", "RBLX", "U", "259960.KS", "DBX", "ZM", "TWLO", "SHOP",
    "GDDY", "WIX", "NET", "AKAM", "UPWK", "FVRR", "TDOC", "MTCH", "BMBL", "ANGI",
    "SSTK", "TTD", "VMEO", "4385.T", "JMIA", "ALE.WA", "ASC.L", "BOO.L",
    "CHWY", "ETSY", "HFG.DE", "JUSTDIAL.NS", "NAUKRI.NS", "069080.KS", "NTES", "YY",
    "035720.KS", "GRPN", "YELP", "TRIP", "SWIGGY.NS", "NYKAA.NS", "PAYTM.NS", "POLICYBZR.NS"
]

# Function to calculate EMA
def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

# Fetch and calculate MACD for a ticker
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="2y")
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

# Fetch data for all tickers
results = [get_stock_data(ticker) for ticker in tickers]

# Add timestamp column
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
results = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], timestamp] for r in results]

# Prepare data for Google Sheets
header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist", "Last Updated"]
body = [header] + results

# Update Google Sheet
sheet = service.spreadsheets()
request = sheet.values().update(
    spreadsheetId=SHEET_ID,
    range="Sheet1!A1:H101",  # 100 tickers + header
    valueInputOption="RAW",
    body={"values": body}
).execute()

print(f"Updated Google Sheet with {len(results)} tickers.")
