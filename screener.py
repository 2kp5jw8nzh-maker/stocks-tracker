#!/usr/bin/env python3
"""
Catalyst-Proximity Screener (v1)
=================================

WHAT THIS IS
------------
A probability-weighted SHORTLIST generator, not a predictor. It surfaces
US stocks with a confirmed upcoming earnings date AND historically elevated
price volatility, and shows you WHY each one was flagged (the raw numbers),
so you can do your own judgment call on top of it.

It does NOT tell you direction (up or down), and it does NOT guarantee a
move of any size. A stock with a history of big earnings swings is not more
likely to swing UP than down -- volatility is a magnitude signal, not a
direction signal. Treat every name in the output as "worth researching
further," never as "buy this."

WHAT IT PULLS (all from Financial Modeling Prep's free tier)
--------------------------------------------------------------
1. Earnings calendar for the next LOOKAHEAD_DAYS days
2. Market cap per company (filters out illiquid micro-caps by default)
3. ~90 days of daily price history per candidate, used to compute
   realized (historical) volatility as a proxy for "how much this stock
   tends to move" -- since true options-implied volatility is not
   reliably available on free API tiers anywhere.
4. Analyst estimate trend (revenue/EPS estimate direction), where available.

WHAT IT DELIBERATELY LEAVES OUT (v1)
--------------------------------------
- Options implied volatility / unusual options activity -- not reliably
  free on any provider. Don't let a later paid add-on fake this in the
  meantime; leave the factor out until it's real.
- Short interest -- same reason; FMP's free tier does not reliably expose
  this. Add later if you upgrade or add a second data source.

USAGE
-----
    export FMP_API_KEY="your_key_here"
    python3 screener.py

Outputs a ranked table to stdout AND writes results.csv with full detail.

SCHEDULING
----------
Wire this into a weekly GitHub Actions cron job (same pattern as any other
scheduled tracker) -- see README.md for a ready-made workflow file.
"""

import os
import sys
import csv
import math
import statistics
from datetime import date, timedelta

from fmp_common import api_get, get_price_history, get_current_price
from finnhub_common import get_finnhub_headlines

# ---- Tunable parameters -----------------------------------------------
LOOKAHEAD_DAYS = 21          # only surface earnings within this many days
MIN_MARKET_CAP = 2_000_000_000   # filter out illiquid micro-caps (2B default)
MAX_MARKET_CAP = None            # set e.g. 50_000_000_000 to focus on smaller names
PRICE_HISTORY_DAYS = 90      # window used to compute realized volatility
TOP_N = 25                   # how many results to print/keep
HEADLINE_TOP_N = 5           # how many top candidates get headlines + logged for tracking
# -------------------------------------------------------------------------


def get_earnings_calendar(days_ahead):
    today = date.today()
    end = today + timedelta(days=days_ahead)
    data = api_get("earnings-calendar", {
        "from": today.isoformat(),
        "to": end.isoformat(),
    })
    if not data:
        return []
    # Keep only US-listed common-stock-looking tickers (no dots/dashes = simplest filter)
    return [row for row in data if row.get("symbol") and "." not in row["symbol"]]


def get_market_cap(symbol):
    data = api_get("profile", {"symbol": symbol})
    if not data or not isinstance(data, list) or not data:
        return None
    return data[0].get("marketCap")


def get_realized_volatility(symbol, days):
    """Annualized realized volatility (%) from daily log returns."""
    end = date.today()
    start = end - timedelta(days=days + 10)  # pad for weekends/holidays
    prices = get_price_history(symbol, start.isoformat(), end.isoformat())
    if not prices or len(prices) < 10:
        return None
    closes = [p["close"] for p in prices]
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1]]
    if len(log_returns) < 5:
        return None
    daily_std = statistics.pstdev(log_returns)
    annualized_pct = daily_std * math.sqrt(252) * 100
    return round(annualized_pct, 1)


def get_estimate_trend(symbol):
    """Rough proxy: compare the two most recent annual EPS estimates if available."""
    data = api_get("analyst-estimates", {"symbol": symbol, "period": "annual"})
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    try:
        newest, prior = data[0], data[1]
        newest_eps = newest.get("epsAvg")
        prior_eps = prior.get("epsAvg")
        if newest_eps is None or prior_eps is None or prior_eps == 0:
            return None
        pct_change = (newest_eps - prior_eps) / abs(prior_eps) * 100
        return round(pct_change, 1)
    except Exception:
        return None


def score_candidate(days_to_earnings, volatility_pct, estimate_trend_pct):
    """
    Transparent, additive scoring -- every point is traceable back to a
    real number, on purpose. No hidden weighting.

    - Closer earnings date -> higher score (within the lookahead window)
    - Higher realized volatility -> higher score (bigger historical swings;
      this is a MAGNITUDE signal only -- it says nothing about direction)
    - Estimate revision trend now cuts BOTH ways: positive trend adds up to
      10 pts, negative trend SUBTRACTS up to 10 pts. Previously a sharply
      negative trend (e.g. -29%) was scored the same as "no data" -- silently
      hiding a real warning sign. Fixed here.
    """
    score = 0.0

    # Proximity: max 40 pts, linearly decaying across the lookahead window
    score += max(0, (LOOKAHEAD_DAYS - days_to_earnings) / LOOKAHEAD_DAYS) * 40

    # Volatility: max 50 pts. Cap lowered from 80% to 60% based on backtest
    # evidence -- your own 18-month volatility-clustering backtest showed the
    # payoff (move size) flattening out well before 80% annualized vol, with
    # Q4's own average sitting at ~52%. Capping closer to where the real
    # data plateaus keeps the score honest instead of over-crediting
    # extreme-but-untested vol readings.
    if volatility_pct is not None:
        score += min(volatility_pct, 60) / 60 * 50

    # Estimate trend: +/-10 pts, symmetric. Positive revisions help,
    # negative revisions hurt -- both are capped at a 20% swing.
    if estimate_trend_pct is not None:
        capped = max(-20, min(estimate_trend_pct, 20))
        score += (capped / 20) * 10

    return round(score, 1)


def main():
    print(f"Fetching earnings calendar for the next {LOOKAHEAD_DAYS} days...")
    calendar_rows = get_earnings_calendar(LOOKAHEAD_DAYS)
    print(f"  {len(calendar_rows)} raw earnings events found.")

    # De-dupe by symbol, keep nearest date per symbol
    by_symbol = {}
    for row in calendar_rows:
        sym = row["symbol"]
        if sym not in by_symbol or row["date"] < by_symbol[sym]["date"]:
            by_symbol[sym] = row

    results = []
    symbols = list(by_symbol.keys())
    print(f"Scoring {len(symbols)} unique symbols (this makes several API calls per symbol)...")

    for i, sym in enumerate(symbols, 1):
        row = by_symbol[sym]
        earnings_date = date.fromisoformat(row["date"])
        days_to_earnings = (earnings_date - date.today()).days
        if days_to_earnings < 0:
            continue

        mcap = get_market_cap(sym)
        if mcap is None:
            continue
        if mcap < MIN_MARKET_CAP:
            continue
        if MAX_MARKET_CAP and mcap > MAX_MARKET_CAP:
            continue

        vol = get_realized_volatility(sym, PRICE_HISTORY_DAYS)
        trend = get_estimate_trend(sym)
        score = score_candidate(days_to_earnings, vol, trend)

        results.append({
            "symbol": sym,
            "earnings_date": row["date"],
            "days_to_earnings": days_to_earnings,
            "market_cap_b": round(mcap / 1e9, 2),
            "realized_vol_annualized_pct": vol,
            "eps_estimate_trend_pct": trend,
            "score": score,
            "eps_estimated": row.get("epsEstimated"),
            "revenue_estimated": row.get("revenueEstimated"),
        })

        if i % 10 == 0:
            print(f"  ...{i}/{len(symbols)} processed")

    results.sort(key=lambda r: r["score"], reverse=True)
    top = results[:TOP_N]

    print("\n" + "=" * 100)
    print(f"TOP {len(top)} CANDIDATES (by proximity + historical volatility -- NOT a buy signal)")
    print("=" * 100)
    header = f"{'SYM':<7}{'EARNINGS':<12}{'DAYS':<6}{'MCAP($B)':<10}{'REAL.VOL%':<11}{'EST.TREND%':<12}{'SCORE':<7}"
    print(header)
    print("-" * 100)
    for r in top:
        print(f"{r['symbol']:<7}{r['earnings_date']:<12}{r['days_to_earnings']:<6}"
              f"{r['market_cap_b']:<10}{str(r['realized_vol_annualized_pct']):<11}"
              f"{str(r['eps_estimate_trend_pct']):<12}{r['score']:<7}")

    # Write full CSV
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv")
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(top[0].keys()) if top else [])
        writer.writeheader()
        writer.writerows(results)
    print(f"\nFull results ({len(results)} candidates) written to {out_path}")

    # ---- Track record logging + best-effort headlines for the top picks ----
    log_and_digest(top[:HEADLINE_TOP_N])

    print("\nReminder: this ranks candidates worth RESEARCHING FURTHER. It does not")
    print("predict direction, and historical volatility does not guarantee a repeat move.")


def log_and_digest(top_picks):
    """
    For the top picks only (to stay light on API calls):
      1. Log this run into history.csv (cumulative, one row per pick per run)
         with the CURRENT price attached, so track_outcomes.py can check back
         later and see what actually happened -- building a real track
         record instead of trusting the score on faith.
      2. Pull best-effort headlines (may silently return nothing if the news
         endpoint isn't available on the free tier) and write digest.txt --
         a short human-readable summary meant for the weekly notification,
         so you can act on it without opening the CSV.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    history_path = os.path.join(base_dir, "history.csv")
    digest_path = os.path.join(base_dir, "digest.txt")
    run_date = date.today().isoformat()

    history_fields = ["run_date", "symbol", "earnings_date", "score", "price_at_flag",
                       "outcome_pct", "outcome_checked_date"]
    file_exists = os.path.exists(history_path)

    digest_lines = [f"Weekly screener run -- {run_date}", "=" * 40]

    with open(history_path, "a", newline="") as hf:
        writer = csv.DictWriter(hf, fieldnames=history_fields)
        if not file_exists:
            writer.writeheader()

        for pick in top_picks:
            sym = pick["symbol"]
            price = get_current_price(sym)
            writer.writerow({
                "run_date": run_date,
                "symbol": sym,
                "earnings_date": pick["earnings_date"],
                "score": pick["score"],
                "price_at_flag": price,
                "outcome_pct": "",          # filled in later by track_outcomes.py
                "outcome_checked_date": "",
            })

            headlines = get_finnhub_headlines(sym, limit=2)
            digest_lines.append(
                f"\n{sym}  (score {pick['score']}, earnings {pick['earnings_date']}, "
                f"price {'$' + str(price) if price else 'n/a'})"
            )
            digest_lines.append(
                f"  vol {pick['realized_vol_annualized_pct']}% | "
                f"est trend {pick['eps_estimate_trend_pct']}%"
            )
            if headlines:
                for h in headlines:
                    digest_lines.append(f"  - {h['title']}")
            else:
                digest_lines.append("  (no headlines available -- check the ticker manually)")

    with open(digest_path, "w") as df:
        df.write("\n".join(digest_lines) + "\n")

    print(f"Logged {len(top_picks)} top picks to {history_path} for future track-record checking.")
    print(f"Digest written to {digest_path}")


if __name__ == "__main__":
    main()
