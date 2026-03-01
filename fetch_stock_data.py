"""
Internet Momentum Portfolio Tracker — fetch_stock_data.py
=========================================================

Portfolio rules:
  Signal:      MACD > 0  AND  Hist > 0
  Max pos:     20
  Entry rank:  Hist / Weekly Close (normalised — fair across all price scales & currencies)
  Hold rule:   NEVER sell a position unless its signal turns OFF
  New entries: Only when capacity exists (held < 20). Fill slots by rank score desc.
  Sizing:      New entry cost = current NAV ÷ total holdings AFTER this week's buys
  Min stocks:  < 10 qualifying → exit ALL, go 100% cash
  Cash re-entry: ≥ 10 qualify → take all qualifying up to 20, ranked
  NAV:         $100,000 starting capital, tracks week-over-week
  Scans:       docs/scans/YYYY-MM-DD.csv — immutable weekly snapshots
  No Google Sheets dependency.
"""

import json
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT            = Path(__file__).parent
DOCS            = ROOT / "docs"
SCANS           = DOCS / "scans"
PORTFOLIO_STATE = DOCS / "portfolio_state.json"
NAV_HISTORY     = DOCS / "nav_history.csv"
TRADE_LOG       = DOCS / "trade_log.csv"
TICKERS_FILE    = ROOT / "tickers.csv"

for d in (DOCS, SCANS):
    d.mkdir(parents=True, exist_ok=True)

# ── Strategy constants ────────────────────────────────────────────────────────
STARTING_NAV  = 100_000.0
MAX_POSITIONS = 20
MIN_STOCKS    = 10
EMA_FAST, EMA_SLOW, EMA_SIG = 12, 26, 9
MARKET_TICKER = "^GSPC"
MARKET_EMA_FAST, MARKET_EMA_SLOW = 10, 20

# ── HTTP session ──────────────────────────────────────────────────────────────
def _make_session():
    try:
        from curl_cffi import requests as cc
        s = cc.Session(impersonate="chrome")
        log.info("HTTP: curl_cffi")
        return s
    except Exception:
        pass
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    log.info("HTTP: requests")
    return s

SESSION = _make_session()

# ── Connectivity ──────────────────────────────────────────────────────────────
def yahoo_reachable() -> bool:
    try:
        r = SESSION.get(
            "https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=10
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("Yahoo Finance unreachable: %s", e)
        return False

# ── Ticker universe ───────────────────────────────────────────────────────────
def load_tickers() -> pd.DataFrame:
    if not TICKERS_FILE.exists():
        raise FileNotFoundError(f"tickers.csv not found at {TICKERS_FILE}")
    df = pd.read_csv(TICKERS_FILE)
    df.columns = [c.strip().lower() for c in df.columns]
    log.info("Loaded %d tickers from tickers.csv", len(df))
    return df

# ── MACD ──────────────────────────────────────────────────────────────────────
def calc_macd(series: pd.Series):
    ema_f  = series.ewm(span=EMA_FAST, adjust=False).mean()
    ema_s  = series.ewm(span=EMA_SLOW, adjust=False).mean()
    macd   = ema_f - ema_s
    signal = macd.ewm(span=EMA_SIG, adjust=False).mean()
    hist   = macd - signal
    return ema_f, ema_s, macd, signal, hist

# ── Fetch one ticker ──────────────────────────────────────────────────────────
RETRYABLE = ["Read timed out", "Too Many Requests", "Rate limited",
             "temporarily unavailable", "Connection reset"]

def fetch_ticker(ticker: str, attempts: int = 3) -> pd.DataFrame:
    for i in range(1, attempts + 1):
        try:
            return yf.Ticker(ticker, session=SESSION).history(
                period="2y", auto_adjust=True
            )
        except Exception as e:
            msg = str(e)
            if any(m.lower() in msg.lower() for m in RETRYABLE) and i < attempts:
                wait = min(2 ** i, 10)
                log.warning("Retry %s/%s for %s in %ss", i, attempts, ticker, wait)
                time.sleep(wait)
            else:
                raise

def get_stock_data(ticker: str, name: str, region: str) -> dict:
    base = {"ticker": ticker, "name": name, "region": region, "momentum": False}
    try:
        log.info("Fetching %-20s  (%s)", ticker, region)
        df = fetch_ticker(ticker)

        if df is None or df.empty:
            return {**base, "status": "no_data"}

        weekly = df["Close"].resample("W-FRI").last().dropna()

        if len(weekly) < EMA_SLOW + EMA_SIG:
            log.warning("Insufficient history for %s (%d weeks)", ticker, len(weekly))
            return {
                **base,
                "weekly_close": round(float(weekly.iloc[-1]), 4) if len(weekly) else None,
                "status": "insufficient_history",
            }

        ema_f, ema_s, macd, signal, hist = calc_macd(weekly)

        close  = round(float(weekly.iloc[-1]),   4)
        e12    = round(float(ema_f.iloc[-1]),    4)
        e26    = round(float(ema_s.iloc[-1]),    4)
        macd_v = round(float(macd.iloc[-1]),     4)
        sig_v  = round(float(signal.iloc[-1]),   4)
        hist_v = round(float(hist.iloc[-1]),     4)

        # Signal: MACD > 0 AND Hist > 0
        momentum = bool((macd_v > 0) and (hist_v > 0))

        # Ranking score: Hist / Close  (normalised — comparable across all prices & currencies)
        rank_score = round(hist_v / close, 6) if close and close != 0 else 0.0

        return {
            **base,
            "weekly_close": close,
            "ema12": e12, "ema26": e26,
            "macd": macd_v, "signal": sig_v, "hist": hist_v,
            "rank_score": rank_score,
            "momentum": momentum,
            "status": "ok",
        }

    except Exception as e:
        log.error("Error fetching %s: %s", ticker, e)
        return {**base, "status": f"error: {e}"}
    finally:
        time.sleep(1.5)


def get_market_trend() -> dict:
    """Market filter: allow entries only when S&P 500 EMA10 >= EMA20."""
    base = {
        "ticker": MARKET_TICKER,
        "ema10": None,
        "ema20": None,
        "risk_on": False,
        "status": "unknown",
    }
    try:
        log.info("Fetching market filter data for %s", MARKET_TICKER)
        df = fetch_ticker(MARKET_TICKER)
        if df is None or df.empty:
            return {**base, "status": "no_data"}

        close = df["Close"].dropna()
        if len(close) < MARKET_EMA_SLOW:
            return {**base, "status": "insufficient_history"}

        ema10 = float(close.ewm(span=MARKET_EMA_FAST, adjust=False).mean().iloc[-1])
        ema20 = float(close.ewm(span=MARKET_EMA_SLOW, adjust=False).mean().iloc[-1])

        return {
            **base,
            "ema10": round(ema10, 4),
            "ema20": round(ema20, 4),
            "risk_on": bool(ema10 >= ema20),
            "status": "ok",
        }
    except Exception as e:
        log.error("Error fetching market filter: %s", e)
        return {**base, "status": f"error: {e}"}

# ── State ─────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if PORTFOLIO_STATE.exists():
        return json.loads(PORTFOLIO_STATE.read_text())
    return {
        "holdings": {},
        # holdings schema: {ticker: {entry_price, entry_date, name, region,
        #                            cost_basis, rank_score_at_entry}}
        "cash": STARTING_NAV,
        "nav": STARTING_NAV,
        "inception_date": str(date.today()),
        "last_run": None,
        "in_cash": False,
    }

def save_state(s: dict):
    PORTFOLIO_STATE.write_text(json.dumps(s, indent=2, default=str))

# ── NAV ───────────────────────────────────────────────────────────────────────
def mark_to_market(state: dict, scan_by_t: dict) -> float:
    """cash + Σ (current_price / entry_price) × cost_basis for each holding."""
    nav = state["cash"]
    for t, pos in state["holdings"].items():
        px = (scan_by_t[t]["weekly_close"]
              if t in scan_by_t and scan_by_t[t].get("weekly_close")
              else pos["entry_price"])
        nav += (px / pos["entry_price"]) * pos["cost_basis"]
    return nav

def load_nav_history() -> pd.DataFrame:
    if NAV_HISTORY.exists():
        return pd.read_csv(NAV_HISTORY)
    return pd.DataFrame(columns=[
        "date", "nav", "weekly_return_pct",
        "num_holdings", "in_cash", "qualifying_count"
    ])

def append_nav(nav_df, run_date, nav, n_held, in_cash, q_count) -> pd.DataFrame:
    prev = float(nav_df["nav"].iloc[-1]) if len(nav_df) else STARTING_NAV
    wret = round((nav / prev - 1) * 100, 4) if prev else 0.0
    row  = pd.DataFrame([{
        "date": str(run_date), "nav": round(nav, 2),
        "weekly_return_pct": wret, "num_holdings": n_held,
        "in_cash": in_cash, "qualifying_count": q_count,
    }])
    return pd.concat([nav_df, row], ignore_index=True)

# ── Trade log ─────────────────────────────────────────────────────────────────
def load_trade_log() -> pd.DataFrame:
    if TRADE_LOG.exists():
        return pd.read_csv(TRADE_LOG)
    return pd.DataFrame(columns=[
        "date", "ticker", "name", "action",
        "price", "cost_basis", "realized_pnl_pct", "reason"
    ])

def record_trade(tdf, run_date, ticker, name, action,
                 price, cost_basis=None, pnl_pct=None, reason="") -> pd.DataFrame:
    row = pd.DataFrame([{
        "date": str(run_date), "ticker": ticker, "name": name, "action": action,
        "price": round(price, 4),
        "cost_basis": round(cost_basis, 4) if cost_basis is not None else "",
        "realized_pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else "",
        "reason": reason,
    }])
    return pd.concat([tdf, row], ignore_index=True)

# ── Portfolio engine ──────────────────────────────────────────────────────────
def run_portfolio(state: dict, scan_results: list,
                  scan_by_t: dict, run_date: date,
                  trade_df: pd.DataFrame, market_trend: dict):
    """
    Returns (updated_trade_df, qualifying_count).
    Mutates state in-place.

    Flow:
      1. Mark NAV to market.
      2. Sell holdings whose signal is OFF.
      3. Check risk gates (< MIN_STOCKS or S&P500 EMA10 < EMA20) → full cash if triggered.
      4. Fill spare capacity (up to MAX_POSITIONS) from ranked candidates.
         Entry size = NAV ÷ (current holdings + new buys).
    """
    holdings = state["holdings"]

    # ── 1. Mark to market ─────────────────────────────────────────────────
    state["nav"] = mark_to_market(state, scan_by_t)
    log.info("NAV (mark-to-market): $%.2f", state["nav"])

    # Build qualifying lookup
    qualifying = {
        r["ticker"]: r for r in scan_results
        if r.get("momentum")
        and r.get("status") == "ok"
        and r.get("weekly_close") is not None
    }
    q_count = len(qualifying)

    # ── 2. Exit positions where signal turned OFF ──────────────────────────
    to_sell = [t for t in list(holdings) if t not in qualifying]
    for t in to_sell:
        pos       = holdings.pop(t)
        sell_px   = (scan_by_t[t]["weekly_close"]
                     if t in scan_by_t and scan_by_t[t].get("weekly_close")
                     else pos["entry_price"])
        pnl_pct   = (sell_px / pos["entry_price"] - 1) * 100
        recovered = (sell_px / pos["entry_price"]) * pos["cost_basis"]
        state["cash"] += recovered
        trade_df = record_trade(
            trade_df, run_date, t, pos.get("name", t),
            "SELL", sell_px, pos["entry_price"], pnl_pct, "signal_off"
        )
        log.info("SELL  %-12s  @ %.4f  P&L %+.2f%%  recovered $%.2f",
                 t, sell_px, pnl_pct, recovered)

    # Re-mark after sells
    state["nav"] = mark_to_market(state, scan_by_t)

    # ── 3. Risk gates ─────────────────────────────────────────────────────
    gate_reasons = []
    if q_count < MIN_STOCKS:
        gate_reasons.append(f"qualifying_lt_{MIN_STOCKS}")
    if not market_trend.get("risk_on", False):
        gate_reasons.append("sp500_ema10_below_ema20")

    if gate_reasons:
        log.warning("Risk gate triggered (%s). Exiting all → cash.", ", ".join(gate_reasons))
        for t in list(holdings):
            pos     = holdings.pop(t)
            sell_px = (scan_by_t[t]["weekly_close"]
                       if t in scan_by_t and scan_by_t[t].get("weekly_close")
                       else pos["entry_price"])
            pnl_pct = (sell_px / pos["entry_price"] - 1) * 100
            state["cash"] += (sell_px / pos["entry_price"]) * pos["cost_basis"]
            trade_df = record_trade(
                trade_df, run_date, t, pos.get("name", t),
                "SELL", sell_px, pos["entry_price"], pnl_pct,
                f"cash_rule_{'+'.join(gate_reasons)}"
            )
            log.info("SELL  %-12s  @ %.4f  (cash rule)", t, sell_px)

        state["nav"]      = state["cash"]
        state["in_cash"]  = True
        state["holdings"] = holdings
        return trade_df, q_count

    state["in_cash"] = False

    # ── 4. Fill spare capacity ─────────────────────────────────────────────
    capacity = MAX_POSITIONS - len(holdings)
    if capacity <= 0:
        log.info("Portfolio full (%d/%d). No new entries this week.",
                 len(holdings), MAX_POSITIONS)
        state["holdings"] = holdings
        return trade_df, q_count

    # Candidates = qualifying but NOT already held
    candidates = [
        r for r in qualifying.values()
        if r["ticker"] not in holdings
    ]
    # Rank by Hist/Close descending
    candidates.sort(key=lambda r: r.get("rank_score", 0), reverse=True)

    slots = min(capacity, len(candidates))
    if slots == 0:
        log.info("No new candidates available.")
        state["holdings"] = holdings
        return trade_df, q_count

    # Entry size: NAV ÷ total holdings after all buys complete
    # (makes the whole portfolio equal-weight at this moment)
    total_after = len(holdings) + slots
    entry_size  = state["nav"] / total_after
    log.info("Buying %d position(s). Entry size: $%.2f (NAV $%.2f ÷ %d)",
             slots, entry_size, state["nav"], total_after)

    for idx, r in enumerate(candidates[:slots]):
        t          = r["ticker"]
        entry_px   = r["weekly_close"]
        cost_basis = round(entry_size, 4)

        holdings[t] = {
            "entry_price":         entry_px,
            "entry_date":          str(run_date),
            "name":                r.get("name", t),
            "region":              r.get("region", ""),
            "cost_basis":          cost_basis,
            "rank_score_at_entry": r.get("rank_score", 0),
        }
        state["cash"] -= cost_basis

        trade_df = record_trade(
            trade_df, run_date, t, r.get("name", t),
            "BUY", entry_px, None, None,
            f"rank_{idx+1}_of_{len(candidates)}"
        )
        log.info("BUY   %-12s  @ %.4f  score=%.6f  cost=$%.2f",
                 t, entry_px, r.get("rank_score", 0), cost_basis)

    state["holdings"] = holdings
    state["nav"]      = mark_to_market(state, scan_by_t)
    return trade_df, q_count

# ── Save immutable scan snapshot ──────────────────────────────────────────────
def save_scan(results: list, run_date: date):
    rows = [{
        "ticker":       r.get("ticker"),
        "name":         r.get("name", ""),
        "region":       r.get("region", ""),
        "weekly_close": r.get("weekly_close", ""),
        "ema12":        r.get("ema12", ""),
        "ema26":        r.get("ema26", ""),
        "macd":         r.get("macd", ""),
        "signal":       r.get("signal", ""),
        "hist":         r.get("hist", ""),
        "rank_score":   r.get("rank_score", ""),
        "momentum":     "Yes" if r.get("momentum") else "No",
        "status":       r.get("status", ""),
    } for r in results]
    path = SCANS / f"{run_date}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    log.info("Scan saved → %s", path)

# ── Dashboard HTML ────────────────────────────────────────────────────────────
def build_html(state, scan_results, nav_df, trade_log_df,
               run_date, warnings, q_count, market_trend):

    holdings = state["holdings"]
    scan_by_t = {r["ticker"]: r for r in scan_results}
    nav          = state["nav"]
    total_return = (nav / STARTING_NAV - 1) * 100
    inception    = state.get("inception_date", "—")
    in_cash      = state.get("in_cash", False)
    latest_wret  = (f'{float(nav_df["weekly_return_pct"].iloc[-1]):+.2f}%'
                    if len(nav_df) else "—")

    # Holdings rows
    holding_rows = []
    for t, pos in sorted(holdings.items()):
        px      = scan_by_t.get(t, {}).get("weekly_close") or pos["entry_price"]
        entry   = pos["entry_price"]
        pnl_pct = (px / entry - 1) * 100
        pnl_usd = (px / entry - 1) * pos["cost_basis"]
        col     = "#4ade80" if pnl_pct >= 0 else "#f87171"
        holding_rows.append(f"""
        <tr>
          <td><strong>{t}</strong></td><td>{pos.get('name','')}</td>
          <td class="mono">{pos.get('region','')}</td>
          <td class="mono">{pos.get('entry_date','')}</td>
          <td class="mono">${entry:,.4f}</td><td class="mono">${px:,.4f}</td>
          <td class="mono" style="color:{col};font-weight:600">{pnl_pct:+.2f}%</td>
          <td class="mono" style="color:{col}">${pnl_usd:+,.0f}</td>
          <td class="mono">${pos.get('cost_basis',0):,.0f}</td>
          <td class="mono">{pos.get('rank_score_at_entry',0):.5f}</td>
        </tr>""")

    # Scan rows — qualifying first, sorted by rank_score desc
    ok = [r for r in scan_results if r.get("status") == "ok"]
    ok.sort(key=lambda r: (-int(r.get("momentum", False)), -r.get("rank_score", 0)))
    scan_rows = []
    for r in ok:
        m    = r.get("momentum", False)
        held = r["ticker"] in holdings
        badge = ('<span class="badge-yes">YES</span>' if m
                 else '<span class="badge-no">NO</span>')
        hbadge = '<span class="badge-held">HELD</span>' if held else ""
        scan_rows.append(f"""
        <tr class="{'row-held' if held else ('row-yes' if m else '')}">
          <td><strong>{r['ticker']}</strong></td><td>{r.get('name','')}</td>
          <td class="mono">{r.get('region','')}</td>
          <td class="mono">${r.get('weekly_close',0):,.4f}</td>
          <td class="mono">{r.get('macd',0):+.4f}</td>
          <td class="mono">{r.get('signal',0):+.4f}</td>
          <td class="mono">{r.get('hist',0):+.4f}</td>
          <td class="mono">{r.get('rank_score',0):.5f}</td>
          <td>{badge} {hbadge}</td>
        </tr>""")

    # Trade log rows
    trade_rows = []
    for _, row in trade_log_df.iloc[::-1].head(300).iterrows():
        ac  = row.get("action", "")
        cls = "action-buy" if ac == "BUY" else "action-sell"
        pnl = row.get("realized_pnl_pct", "")
        pnl_html = ""
        if str(pnl) not in ("", "nan"):
            v   = float(pnl)
            col = "#4ade80" if v >= 0 else "#f87171"
            pnl_html = f'<span style="color:{col};font-weight:600">{v:+.2f}%</span>'
        trade_rows.append(f"""
        <tr>
          <td class="mono">{row.get('date','')}</td>
          <td><strong>{row.get('ticker','')}</strong></td>
          <td>{row.get('name','')}</td>
          <td><span class="{cls}">{ac}</span></td>
          <td class="mono">${float(row.get('price',0)):,.4f}</td>
          <td>{pnl_html}</td>
          <td class="mono" style="color:var(--muted);font-size:11px">{row.get('reason','')}</td>
        </tr>""")

    nav_json = json.dumps({
        "dates":    list(nav_df["date"]),
        "values":   [float(v) for v in nav_df["nav"]],
        "returns":  [float(v) for v in nav_df["weekly_return_pct"]],
        "holdings": [int(v)   for v in nav_df["num_holdings"]],
    })

    warn_html = ""
    if warnings:
        items = "".join(f"<li>{w}</li>" for w in warnings)
        warn_html = (f'<div class="warn-box"><strong>⚠ Data Warnings ({len(warnings)})</strong>'
                     f'<ul>{items}</ul></div>')

    cash_reasons = []
    if q_count < MIN_STOCKS:
        cash_reasons.append(f"only {q_count} stocks qualified this week (minimum {MIN_STOCKS} required)")
    if not market_trend.get("risk_on", False):
        e10 = market_trend.get("ema10")
        e20 = market_trend.get("ema20")
        if e10 is not None and e20 is not None:
            cash_reasons.append(f"S&amp;P 500 EMA{MARKET_EMA_FAST} ({e10:.2f}) is below EMA{MARKET_EMA_SLOW} ({e20:.2f})")
        else:
            cash_reasons.append(f"S&amp;P 500 EMA{MARKET_EMA_FAST} is below EMA{MARKET_EMA_SLOW}")

    cash_banner = (
        '<div class="cash-banner">⚠ PORTFOLIO IN CASH — ' + " and ".join(cash_reasons) + ". All positions exited.</div>"
        if in_cash and cash_reasons else ""
    )

    ok_count = len([r for r in scan_results if r.get("status") == "ok"])
    cap_pct  = int(len(holdings) / MAX_POSITIONS * 100)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Internet Momentum Portfolio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Manrope:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#07080d;--s1:#0f1018;--s2:#171820;--border:#23242f;--border2:#2e3040;
      --green:#4ade80;--red:#f87171;--blue:#60a5fa;--amber:#fbbf24;--purple:#a78bfa;
      --text:#dde1ed;--muted:#5a6070;--muted2:#3a3f50}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Manrope',sans-serif;font-size:14px;line-height:1.65}}
.mono{{font-family:'IBM Plex Mono',monospace}}
.wrap{{max-width:1440px;margin:0 auto;padding:36px 28px}}
.hdr{{display:flex;justify-content:space-between;align-items:flex-end;
      padding-bottom:28px;border-bottom:1px solid var(--border);margin-bottom:36px}}
.hdr h1{{font-size:clamp(20px,3.5vw,36px);font-weight:800;letter-spacing:-1.5px;
         background:linear-gradient(120deg,var(--green),var(--blue));
         -webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hdr p{{font-size:11px;color:var(--muted);margin-top:4px;font-family:'IBM Plex Mono',monospace}}
.hdr-r{{text-align:right;font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--muted);line-height:1.9}}
.stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:14px;margin-bottom:36px}}
.card{{background:var(--s1);border:1px solid var(--border);border-radius:14px;padding:18px 20px;transition:border-color .2s}}
.card:hover{{border-color:var(--border2)}}
.card .lbl{{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}}
.card .val{{font-size:23px;font-weight:800;font-family:'IBM Plex Mono',monospace;line-height:1}}
.card .sub{{font-size:11px;color:var(--muted);margin-top:6px;font-family:'IBM Plex Mono',monospace}}
.green{{color:var(--green)}}.red{{color:var(--red)}}.blue{{color:var(--blue)}}.amber{{color:var(--amber)}}
.cap-track{{background:var(--s2);border-radius:99px;height:5px;overflow:hidden;margin-top:10px}}
.cap-fill{{background:linear-gradient(90deg,var(--green),var(--blue));height:100%;border-radius:99px}}
.section{{margin-bottom:44px}}
.sec-hdr{{display:flex;align-items:center;gap:12px;margin-bottom:14px}}
.sec-hdr h2{{font-size:15px;font-weight:700;letter-spacing:-.3px}}
.tag{{font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
      background:var(--s2);border:1px solid var(--border);color:var(--muted);
      border-radius:99px;padding:3px 10px;white-space:nowrap}}
.chart-box{{background:var(--s1);border:1px solid var(--border);border-radius:16px;padding:24px}}
.tbl-wrap{{overflow-x:auto;border-radius:12px;border:1px solid var(--border)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
thead{{background:var(--s2)}}
th{{padding:10px 13px;text-align:left;font-size:10px;font-weight:700;
    letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
    border-bottom:1px solid var(--border);white-space:nowrap}}
tr{{border-bottom:1px solid var(--border);transition:background .12s}}
tr:last-child{{border-bottom:none}}
tr:hover{{background:var(--s2)}}
tr.row-yes{{background:rgba(74,222,128,.03)}}
tr.row-held{{background:rgba(96,165,250,.05);border-left:2px solid var(--blue)}}
td{{padding:9px 13px;vertical-align:middle}}
.badge-yes{{background:rgba(74,222,128,.15);color:var(--green);border:1px solid rgba(74,222,128,.3);
            border-radius:5px;padding:2px 7px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace}}
.badge-no{{background:rgba(248,113,113,.1);color:var(--red);border:1px solid rgba(248,113,113,.2);
           border-radius:5px;padding:2px 7px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace}}
.badge-held{{background:rgba(96,165,250,.15);color:var(--blue);border:1px solid rgba(96,165,250,.3);
             border-radius:5px;padding:2px 7px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace}}
.action-buy{{background:rgba(74,222,128,.12);color:var(--green);border-radius:4px;
             padding:2px 8px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace}}
.action-sell{{background:rgba(248,113,113,.1);color:var(--red);border-radius:4px;
              padding:2px 8px;font-size:10px;font-weight:700;font-family:'IBM Plex Mono',monospace}}
.warn-box{{background:rgba(251,191,36,.07);border:1px solid rgba(251,191,36,.25);
           border-radius:10px;padding:14px 18px;margin-bottom:20px;color:var(--amber)}}
.warn-box ul{{padding-left:18px;margin-top:6px;font-family:'IBM Plex Mono',monospace;font-size:12px}}
.cash-banner{{background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.3);
              border-radius:12px;padding:18px 24px;margin-bottom:24px;
              text-align:center;font-size:14px;font-weight:700;color:var(--amber)}}
footer{{margin-top:60px;padding-top:22px;border-top:1px solid var(--border);
        font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace;
        text-align:center;line-height:1.9}}
@media(max-width:640px){{.hdr{{flex-direction:column;align-items:flex-start;gap:10px}}.hdr-r{{text-align:left}}}}
</style>
</head>
<body><div class="wrap">

<div class="hdr">
  <div>
    <h1>Internet Momentum Portfolio</h1>
    <p>Signal: MACD&gt;0 AND Hist&gt;0 · Weekly · Rank: Hist/Close · Max {MAX_POSITIONS} positions · Hold until signal off · S&amp;P500 EMA{MARKET_EMA_FAST}&ge;EMA{MARKET_EMA_SLOW} filter</p>
  </div>
  <div class="hdr-r">Last scan: {run_date}<br>Inception: {inception}<br>Starting NAV: $100,000</div>
</div>

{warn_html}{cash_banner}

<div class="stat-grid">
  <div class="card"><div class="lbl">Portfolio NAV</div>
    <div class="val blue">${nav:,.0f}</div><div class="sub">from $100,000</div></div>
  <div class="card"><div class="lbl">Total Return</div>
    <div class="val {'green' if total_return>=0 else 'red'}">{total_return:+.2f}%</div>
    <div class="sub">since inception</div></div>
  <div class="card"><div class="lbl">This Week</div>
    <div class="val {'green' if latest_wret and latest_wret[0]=='+' else 'red'}">{latest_wret}</div>
    <div class="sub">weekly return</div></div>
  <div class="card"><div class="lbl">Holdings</div>
    <div class="val blue">{len(holdings)}<span style="font-size:14px;color:var(--muted)">/{MAX_POSITIONS}</span></div>
    <div class="cap-track"><div class="cap-fill" style="width:{cap_pct}%"></div></div></div>
  <div class="card"><div class="lbl">Qualifying</div>
    <div class="val {'amber' if q_count<MIN_STOCKS else 'green'}">{q_count}</div>
    <div class="sub">of {ok_count} scanned</div></div>
  <div class="card"><div class="lbl">Universe</div>
    <div class="val blue">{len(scan_results)}</div><div class="sub">tickers tracked</div></div>
</div>

<div class="section">
  <div class="sec-hdr"><h2>NAV History</h2><span class="tag">$100k starting capital</span></div>
  <div class="chart-box"><canvas id="navChart" height="75"></canvas></div>
</div>

<div class="section">
  <div class="sec-hdr"><h2>Current Holdings</h2>
    <span class="tag">{len(holdings)} positions · equal weight at entry · hold until signal off</span></div>
  {'<p style="padding:20px;color:var(--muted);font-family:IBM Plex Mono,monospace">No positions — portfolio in cash.</p>' if not holding_rows else f'''
  <div class="tbl-wrap"><table>
    <thead><tr><th>Ticker</th><th>Name</th><th>Region</th><th>Entry Date</th>
      <th>Entry Price</th><th>Current</th><th>P&L %</th><th>P&L $</th>
      <th>Cost Basis</th><th>Rank Score</th></tr></thead>
    <tbody>{"".join(holding_rows)}</tbody></table></div>'''}
</div>

<div class="section">
  <div class="sec-hdr"><h2>This Week's Scan</h2>
    <span class="tag">{q_count} qualifying · sorted by rank score</span></div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Ticker</th><th>Name</th><th>Region</th><th>Close</th>
      <th>MACD</th><th>Signal</th><th>Hist</th><th>Rank Score</th><th>Status</th></tr></thead>
    <tbody>{"".join(scan_rows)}</tbody></table></div>
</div>

<div class="section">
  <div class="sec-hdr"><h2>Trade Log</h2><span class="tag">most recent first</span></div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Date</th><th>Ticker</th><th>Name</th><th>Action</th>
      <th>Price</th><th>P&L %</th><th>Reason</th></tr></thead>
    <tbody>{"".join(trade_rows) if trade_rows
      else '<tr><td colspan="7" style="color:var(--muted);padding:20px;font-family:IBM Plex Mono,monospace">No trades yet.</td></tr>'
    }</tbody></table></div>
</div>

<footer>
  Internet Momentum Portfolio · MACD&gt;0 AND Hist&gt;0 (EMA {EMA_FAST}/{EMA_SLOW}/{EMA_SIG}, Weekly) ·
  Ranked Hist/Close · Max {MAX_POSITIONS} positions · Min {MIN_STOCKS} to stay invested ·
  Hold until signal off · Cash if S&amp;P500 EMA{MARKET_EMA_FAST}&lt;EMA{MARKET_EMA_SLOW} · $100k NAV · Not financial advice.
</footer></div>

<script>
const D={nav_json};
const ctx=document.getElementById('navChart').getContext('2d');
const g=ctx.createLinearGradient(0,0,0,280);
g.addColorStop(0,'rgba(74,222,128,.22)');g.addColorStop(1,'rgba(74,222,128,0)');
new Chart(ctx,{{type:'line',
  data:{{labels:D.dates,datasets:[{{label:'NAV',data:D.values,
    borderColor:'#4ade80',backgroundColor:g,borderWidth:2,
    pointRadius:D.dates.length>26?0:4,pointHoverRadius:6,
    pointBackgroundColor:'#4ade80',tension:.35,fill:true}}]}},
  options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
    plugins:{{legend:{{display:false}},tooltip:{{
      backgroundColor:'#0f1018',borderColor:'#23242f',borderWidth:1,
      titleColor:'#4ade80',bodyColor:'#dde1ed',
      callbacks:{{
        label:c=>' NAV: $'+c.parsed.y.toLocaleString(undefined,{{maximumFractionDigits:0}}),
        afterLabel:c=>{{
          const r=D.returns[c.dataIndex],h=D.holdings[c.dataIndex];
          return[' Week: '+(r>=0?'+':'')+r.toFixed(2)+'%',' Holdings: '+h];
        }}
      }}
    }}}},
    scales:{{
      x:{{grid:{{color:'#23242f'}},ticks:{{color:'#5a6070',font:{{family:'IBM Plex Mono',size:11}},maxTicksLimit:14}}}},
      y:{{grid:{{color:'#23242f'}},ticks:{{color:'#5a6070',font:{{family:'IBM Plex Mono',size:11}},
           callback:v=>'$'+v.toLocaleString()}}}}
    }}
  }}
}});
</script></body></html>"""

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    run_date = date.today()
    log.info("=" * 60)
    log.info("Internet Momentum Tracker  —  %s", run_date)
    log.info("=" * 60)

    tickers_df = load_tickers()

    if not yahoo_reachable():
        log.error("Aborting — Yahoo Finance unreachable.")
        return

    scan_results, warnings = [], []
    for _, row in tickers_df.iterrows():
        r = get_stock_data(
            str(row["ticker"]).strip(),
            str(row.get("name", row["ticker"])).strip(),
            str(row.get("region", "")).strip(),
        )
        scan_results.append(r)
        if r.get("status") not in ("ok",):
            warnings.append(f"{r['ticker']}: {r['status']}")

    save_scan(scan_results, run_date)
    scan_by_t = {r["ticker"]: r for r in scan_results}

    q_count = sum(
        1 for r in scan_results
        if r.get("momentum") and r.get("status") == "ok"
    )
    log.info("Qualifying: %d / %d", q_count, len(scan_results))

    market_trend = get_market_trend()
    if market_trend.get("status") != "ok":
        warnings.append(f"{MARKET_TICKER}: {market_trend.get('status')}")
    log.info(
        "Market filter (%s): EMA%d=%.4f EMA%d=%.4f -> %s",
        MARKET_TICKER,
        MARKET_EMA_FAST,
        market_trend.get("ema10") if market_trend.get("ema10") is not None else float("nan"),
        MARKET_EMA_SLOW,
        market_trend.get("ema20") if market_trend.get("ema20") is not None else float("nan"),
        "RISK-ON" if market_trend.get("risk_on", False) else "RISK-OFF",
    )

    state        = load_state()
    nav_df       = load_nav_history()
    trade_log_df = load_trade_log()

    trade_log_df, q_count = run_portfolio(
        state, scan_results, scan_by_t, run_date, trade_log_df, market_trend
    )
    state["last_run"] = str(run_date)

    nav_df = append_nav(
        nav_df, run_date, state["nav"],
        len(state["holdings"]), state.get("in_cash", False), q_count
    )

    save_state(state)
    nav_df.to_csv(NAV_HISTORY, index=False)
    trade_log_df.to_csv(TRADE_LOG, index=False)

    log.info("NAV: $%.2f  |  Holdings: %d/%d  |  Cash: $%.2f",
             state["nav"], len(state["holdings"]), MAX_POSITIONS, state["cash"])

    html = build_html(state, scan_results, nav_df, trade_log_df,
                      run_date, warnings, q_count, market_trend)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    log.info("Dashboard written → docs/index.html")
    log.info("Done. ✓")

if __name__ == "__main__":
    main()
