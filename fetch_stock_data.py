import yfinance as yf
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import json

# Google Sheets setup
SHEET_ID = '1wiVMF-bOePDKeaKpQx46FsjZ9pMn1C0RqpnxjNiajmw'  # Your Sheet ID
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)

# Ticker list (your 100 stocks)
tickers = [
    "GOOGL", "META", "AMZN", "BABA", "HKG:0700", "NFLX", "BIDU", "JD", "EBAY", "MELI",
    "SE", "TYO:4755", "ETR:ZAL", "CPNG", "HKG:3690", "PDD", "W", "SNAP", "PINS", "RDDT",
    "HKG:1024", "KRX:035420", "SPOT", "TME", "BILI", "ROKU", "HUYA", "IQ", "BKNG", "EXPE",
    "TCOM", "ABNB", "MMYT", "TRVG", "DESP", "PYPL", "SQ", "AEX:ADYEN", "NU", "COIN",
    "HOOD", "SOFI", "NSE:ZOMATO", "DASH", "ETR:DHER", "AEX:TKWY", "UBER", "LYFT", "GRAB",
    "AEX:PRX", "OSE:ADE", "ZG", "ASX:REA", "LSE:RMV", "CARG", "LSE:AUTO", "TYO:3659",
    "KRX:036570", "TTWO", "EA", "RBLX", "U", "KRX:259960", "DBX", "ZM", "TWLO", "SHOP",
    "GDDY", "WIX", "NET", "AKAM", "SQSP", "UPWK", "FVRR", "TDOC", "MTCH", "BMBL", "ANGI",
    "SSTK", "TTD", "VMEO", "DCT", "TYO:4385", "JMIA", "WSE:ALE", "LSE:ASC", "LSE:BOO",
    "CHWY", "ETSY", "ETR:HFG", "NSE:JUSTDIAL", "NSE:NAUKRI", "KRX:069080", "NTES", "YY",
    "YNDX", "KRX:035720", "GRPN", "YELP", "TRIP"
]

# Function to calculate EMA
def calculate_ema(data, period):
    return data.ewm(span=period, adjust=False).mean()

# Fetch and calculate MACD for a ticker
def get_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="2y")  # 2 years for sufficient weekly data
        if df.empty:
            return [ticker, "No Data", 0, 0, 0, 0, 0]
        
        # Resample to weekly (Friday close)
        weekly = df['Close'].resample('W-FRI').last().dropna()
        
        # Calculate MACD
        ema12 = calculate_ema(weekly, 12)
        ema26 = calculate_ema(weekly, 26)
        macd = ema12 - ema26
        signal = calculate_ema(macd, 9)
        hist = macd - signal
        
        return [
            ticker,
            round(weekly.iloc[-1], 2) if not weekly.empty else "No Data",
            round(ema12.iloc[-1], 2) if not ema12.empty else 0,
            round(ema26.iloc[-1], 2) if not ema26.empty else 0,
            round(macd.iloc[-1], 2) if not macd.empty else 0,
            round(signal.iloc[-1], 2) if not signal.empty else 0,
            round(hist.iloc[-1], 2) if not hist.empty else 0
        ]
    except Exception as e:
        return [ticker, f"Error: {str(e)}", 0, 0, 0, 0, 0]

# Fetch data for all tickers
results = [get_stock_data(ticker) for ticker in tickers]

# Prepare data for Google Sheets
header = ["Ticker", "Weekly Close", "EMA12", "EMA26", "MACD", "Signal", "Hist"]
body = [header] + results

# Update Google Sheet
sheet = service.spreadsheets()
request = sheet.values().update(
    spreadsheetId=SHEET_ID,
    range="Sheet1!A1:G101",  # Targeting Sheet1, adjust if tab name differs
    valueInputOption="RAW",
    body={"values": body}
).execute()

print(f"Updated Google Sheet with {len(results)} tickers.")