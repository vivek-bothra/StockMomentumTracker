# Internet Momentum Portfolio Tracker

Momentum portfolio tracking for a global internet stock universe, using a MACD-based weekly signal.

---

## Strategy Rules

| Parameter | Value |
|-----------|-------|
| Signal | MACD > 0 AND Hist > 0 (MACD line above zero AND above Signal line) |
| Rebalancing | Full equal-weight rebalance every week |
| Minimum stocks | < 10 qualifying → move 100% to cash |
| Starting NAV | $100,000 hypothetical |
| MACD inputs | EMA 12 / EMA 26 / Signal 9 — all on weekly closes |
| Schedule | Every Saturday at 02:00 UTC (after Friday US close settles) |

---

## Repository Structure

```
├── fetch_stock_data.py          # Main script — scan + portfolio engine
├── tickers.csv                  # Editable ticker universe
├── requirements.txt
├── .github/
│   └── workflows/
│       ├── weekly_scan.yml      # Runs every Saturday
│       └── deploy_pages.yml     # Deploys docs/ to GitHub Pages
└── docs/
    ├── index.html               # Dashboard (rebuilt each run)
    ├── portfolio_state.json     # Current holdings + NAV
    ├── nav_history.csv          # Week-by-week NAV record
    ├── trade_log.csv            # All buys and sells with P&L
    └── scans/
        └── YYYY-MM-DD.csv       # Immutable weekly scan snapshots
```

---

## Managing the Ticker Universe

Edit `tickers.csv` directly in GitHub's web UI (click the file → pencil icon → commit).

Format:
```csv
ticker,name,region
GOOGL,Alphabet,US
0700.HK,Tencent,HK
```

The script picks up changes automatically on the next Saturday run.  
You can also trigger a manual run: **Actions → Weekly Momentum Scan → Run workflow**.

---

## First-Time Setup

### 1. Fork / clone this repository

Make it **private** if you want the underlying data files private too.

### 2. Enable GitHub Pages

Go to **Settings → Pages → Source → GitHub Actions**.

### 3. Trigger first run

**Actions → Weekly Momentum Scan → Run workflow**

This sets the inception date and creates all the data files.

---

## Dashboard Access Control (Cloudflare Access)

The GitHub Pages URL is public by default. To restrict it to approved email addresses:

### Step 1 — Add your site to Cloudflare (free)

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) and create a free account.
2. Add your GitHub Pages domain (e.g. `yourusername.github.io`) as a website.
   - Choose the **Free** plan.
   - Cloudflare will give you two nameservers — update these at your domain registrar if using a custom domain.
   - If using the default `github.io` subdomain, skip DNS and use a **Cloudflare Tunnel** instead (see Option B below).

### Option A — Custom domain (recommended)

1. In your repo: **Settings → Pages → Custom domain** → enter your domain (e.g. `portfolio.yourdomain.com`).
2. In Cloudflare DNS: add a `CNAME` record pointing `portfolio` → `yourusername.github.io`.
3. Cloudflare now proxies all traffic to your dashboard.

### Step 2 — Enable Cloudflare Access

1. In Cloudflare dashboard: **Zero Trust → Access → Applications → Add an Application**.
2. Choose **Self-hosted**.
3. Set:
   - Application name: `Momentum Portfolio`
   - Application domain: your custom domain (e.g. `portfolio.yourdomain.com`)
4. Under **Policies**, create a policy:
   - Policy name: `Email allowlist`
   - Action: `Allow`
   - Rule: `Emails` → add each permitted email address
5. Save.

From now on, anyone visiting the URL gets a Cloudflare login page. Permitted emails receive a one-time magic link — no password needed.

### Adding / removing users

**Zero Trust → Access → Applications → [your app] → Policies → Edit**  
Add or remove email addresses. Changes take effect immediately.

### Option B — No custom domain (Cloudflare Tunnel)

If you don't want a custom domain, use a Cloudflare Tunnel:

1. **Zero Trust → Networks → Tunnels → Create a tunnel**
2. Install `cloudflared` on any small VM or even your laptop (only needs to run when you want the site accessible — or use a free Oracle Cloud VM).
3. Point the tunnel at `https://yourusername.github.io`.
4. Then apply an Access policy to the tunnel hostname exactly as in Step 2 above.

---

## How the Portfolio Engine Works

Each Saturday:

1. **Scan** — fetch 2 years of weekly closes for all tickers in `tickers.csv`, calculate MACD.
2. **Signal** — a stock qualifies if: `MACD > 0` AND `Hist > 0`.
3. **Gate** — if fewer than 10 stocks qualify, exit all positions, hold cash, do nothing else.
4. **Rebalance** — sell anything no longer qualifying, buy new entrants, equal-weight across all qualifying stocks.
5. **NAV** — mark-to-market all positions using this week's closes, append to `nav_history.csv`.
6. **Save** — write `portfolio_state.json`, `trade_log.csv`, `docs/scans/YYYY-MM-DD.csv`, rebuild `docs/index.html`.
7. **Commit** — GitHub Actions commits the updated `docs/` folder and pushes.
8. **Deploy** — the deploy workflow publishes the new `docs/` to GitHub Pages automatically.

---

## Manual Backtest / Replay

Each weekly scan is saved immutably to `docs/scans/YYYY-MM-DD.csv`. You can replay the full history by processing these files in date order to reconstruct the exact NAV history.

---

## Removing Google Sheets

Google Sheets integration has been removed. The repo itself is now the source of truth:
- Weekly scan data: `docs/scans/`
- Portfolio state: `docs/portfolio_state.json`
- Performance history: `docs/nav_history.csv`
- Trade log: `docs/trade_log.csv`

All files are version-controlled, auditable, and human-readable.

---

## Disclaimer

This is a model portfolio tracker for research and educational purposes. Not financial advice.
