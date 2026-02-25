# Internet Momentum Portfolio Tracker

This project is a simple **weekly stock tracker**.  
It checks a list of internet-related stocks, picks the ones that look strong, and updates a model portfolio automatically.

Think of it like a scoreboard for a rules-based investing experiment.

---

## What this tracker does (in plain English)

Every Saturday, the script:

1. Looks at all stocks in `tickers.csv`
2. Checks a momentum signal (MACD)
3. Keeps only stocks that pass the rule
4. If too few pass, moves everything to cash
5. Otherwise, splits money equally across the passing stocks
6. Updates performance history, trade log, and dashboard files
7. Publishes the dashboard through GitHub Pages

---

## The main rules

- Start with a fake portfolio value of **$100,000**
- Recheck and rebalance **once per week**
- A stock must pass both of these to qualify:
  - MACD is above 0
  - MACD is above its signal line (histogram > 0)
- If **fewer than 10 stocks** qualify, the model goes **100% cash**

> This is fully rule-based. No manual stock picking once the list is set.

---

## Files you should know

- `fetch_stock_data.py` → main engine (scan + portfolio update)
- `tickers.csv` → your editable stock list
- `docs/index.html` → web dashboard
- `docs/portfolio_state.json` → current holdings and cash
- `docs/nav_history.csv` → portfolio value over time
- `docs/trade_log.csv` → buy/sell history
- `docs/scans/YYYY-MM-DD.csv` → weekly scan snapshots

---

## How to change the stock list

Edit `tickers.csv` directly in GitHub.

Format:

```csv
ticker,name,region
GOOGL,Alphabet,US
0700.HK,Tencent,HK
```

Once saved, the next weekly run will use the new list.

---

## Quick setup

1. Fork or clone this repo
2. In GitHub, enable **Pages**:
   - `Settings → Pages → Source → GitHub Actions`
3. Start first run manually:
   - `Actions → Weekly Momentum Scan → Run workflow`

After the first run, the dashboard/data files are created and future runs happen automatically.

---

## If you want the dashboard private

GitHub Pages is public by default.

To restrict access, put the site behind **Cloudflare Access** and allow only selected email addresses.

High-level flow:

1. Add your Pages site to Cloudflare
2. Create a Cloudflare Access app for your dashboard URL
3. Add an allowlist policy with approved emails

Then visitors must verify by email before they can view the dashboard.

---

## How the automation works

- `weekly_scan.yml` runs every Saturday (after US market close)
- It updates `docs/` data files
- GitHub Actions commits the new files
- `deploy_pages.yml` publishes the updated dashboard

So the site stays current with no manual weekly work.

---

## Notes

- This is a **research/education** project, not financial advice
- Results are from a model portfolio, not a live managed account
