name: Weekly Stock Data Update

on:
  schedule:
    - cron: '0 0 * * 6' # Runs every Saturday at midnight UTC
  workflow_dispatch: # Allows manual triggering

jobs:
  update-sheet:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install yfinance google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client pandas

      - name: Run script
        env:
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_CREDENTIALS }}
        run: |
          echo "$GOOGLE_CREDENTIALS" > credentials.json
          python fetch_stock_data.py
