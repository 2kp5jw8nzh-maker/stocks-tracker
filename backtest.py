#!/usr/bin/env python3
"""
Backtest (v2 -- free-tier-only redesign)
==========================================

WHY THIS VERSION EXISTS
-------------------------
v1 tried to test "does pre-earnings volatility predict the post-earnings
move," but FMP's free tier paywalls HISTORICAL earnings-calendar data
entirely (confirmed via live 402 errors -- see project history). Upgrading
to a paid plan would fix that specific test; this version instead answers
a related, still-relevant question using data that IS free: historical
daily prices, with no depth restriction on the free tier.

THE QUESTION THIS ANSWERS
--------------------------
"Does a stock's realized volatility over the past ~90 days predict the
size of its price move over the NEXT few days?" This is a well-documented
phenomenon in finance called volatility clustering -- periods of high
volatility tend to be followed by more high volatility, and calm periods
by more calm. It is NOT specific to earnings, and it says nothing about
DIRECTION -- only magnitude. This is exactly the bet the screener's
volatility factor is making, just tested generally instead of only around
earnings dates.

WHY NOT JUST DETECT "BIG MOVE DAYS" AND CALL THOSE EVENTS?
-------------------------------------------------------------
That would be circular: selecting days by the size of their move, then
checking whether those days had big moves, proves nothing. This script
instead samples checkpoints at REGULAR intervals (every ~21 trading days,
matching the screener's lookahead window) regardless of what happens next,
which avoids that bias.

METHOD
------
For each ticker, walk through ~18 months of daily closes in fixed steps:
  1. At each checkpoint, compute realized volatility from the PRIOR 90
     trading days (no lookahead).
  2. Compute the actual price move over the NEXT 1 and 5 trading days.
  3. Bucket all checkpoints (across all tickers) into volatility quartiles
     and compare the average subsequent move per quartile.

If Q4 (highest pre-vol) shows a clearly larger average subsequent move
than Q1 (lowest pre-vol), the screener's volatility factor is picking up
on a real, general pattern. If the quartiles look similar, it isn't, and
the factor should be reduced or dropped.

LIMITATIONS
------------
- This tests volatility persistence in GENERAL, not specifically around
  earnings. A stock could show strong volatility clustering overall while
  earnings-day moves specifically behave differently -- this backtest
  can't distinguish that without paid earnings-date data.
- Sample size depends on how much history FMP's free tier actually
  returns per request; the script reports how many checkpoints it
  collected so you can judge that for yourself.
- Past patterns can change -- re-run this every few months.

USAGE
-----
    export FMP_API_KEY="your_key_here"
    python3 backtest.py
"""

import sys
import math
import statistics
from datetime import date, timedelta

from fmp_common import get_price_history

# ---- Tunable parameters -----------------------------------------------
HISTORY_DAYS = 540             # ~18 months of calendar days to pull per ticker
PRE_VOL_WINDOW = 90            # trading days used to compute "pre" realized vol
STEP_TRADING_DAYS = 21         # spacing between checkpoints (matches screener's LOOKAHEAD_DAYS)
POST_WINDOWS = [1, 5]          # trading days after each checkpoint to measure the move
SAMPLE_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "JPM", "BAC", "GS",
    "WFC", "C", "JNJ", "UNH", "PFE", "COST", "NKE", "DAL", "UAL", "CAT",
    "BA", "GE", "XOM", "CVX", "V", "MA", "PYPL", "DIS", "NFLX", "AMD", "INTC",
]
# -------------------------------------------------------------------------


def annualized_vol(closes):
    """Annualized realized volatility (%) from a list of closes, using log returns."""
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1]]
    if len(log_returns) < 10:
        return None
    return statistics.pstdev(log_returns) * math.sqrt(252) * 100


def collect_checkpoints(symbol):
    """Walk one ticker's price history and yield (pre_vol, {n: move_pct}) tuples."""
    end = date.today()
    start = end - timedelta(days=HISTORY_DAYS)
    prices = get_price_history(symbol, start.isoformat(), end.isoformat())
    if not prices or len(prices) < PRE_VOL_WINDOW + max(POST_WINDOWS) + 20:
        return []

    closes = [p["close"] for p in prices]
    events = []
    max_post = max(POST_WINDOWS)

    i = PRE_VOL_WINDOW
    while i + max_post < len(closes):
        pre_window = closes[i - PRE_VOL_WINDOW:i]
        vol = annualized_vol(pre_window)
        if vol is not None:
            base = closes[i]
            moves = {n: abs(closes[i + n] - base) / base * 100 for n in POST_WINDOWS}
            events.append((vol, moves))
        i += STEP_TRADING_DAYS

    return events


def main():
    print(f"Testing volatility clustering across {len(SAMPLE_TICKERS)} tickers "
          f"(~{HISTORY_DAYS} days of history each, free-tier data only)...")

    all_events = []
    for i, sym in enumerate(SAMPLE_TICKERS, 1):
        events = collect_checkpoints(sym)
        print(f"  [{i}/{len(SAMPLE_TICKERS)}] {sym}: {len(events)} checkpoint(s)")
        for vol, moves in events:
            all_events.append({"symbol": sym, "pre_vol": vol, **moves})

    if len(all_events) < 20:
        sys.exit(f"Only {len(all_events)} usable checkpoints found -- too few to say anything. "
                  f"Check for API warnings above, or the free tier may be returning less "
                  f"history than expected.")

    print(f"\n{len(all_events)} usable checkpoints collected across all tickers.\n")

    all_events.sort(key=lambda e: e["pre_vol"])
    q_size = max(1, len(all_events) // 4)
    quartiles = [all_events[i:i + q_size] for i in range(0, len(all_events), q_size)]
    if len(quartiles) > 4:
        quartiles[3].extend(quartiles.pop())

    print("=" * 78)
    print("DOES PAST VOLATILITY PREDICT NEAR-TERM FUTURE MOVE SIZE? (volatility clustering)")
    print("=" * 78)
    print(f"{'Quartile':<14}{'Avg pre-vol%':<15}{'Avg 1d move%':<15}{'Avg 5d move%':<15}{'n':<5}")
    print("-" * 78)
    for idx, q in enumerate(quartiles, 1):
        avg_vol = statistics.mean(e["pre_vol"] for e in q)
        avg_1d = statistics.mean(e[1] for e in q if 1 in e)
        avg_5d = statistics.mean(e[5] for e in q if 5 in e)
        label = f"Q{idx}" + (" (lowest)" if idx == 1 else " (highest)" if idx == len(quartiles) else "")
        print(f"{label:<14}{avg_vol:<15.1f}{avg_1d:<15.2f}{avg_5d:<15.2f}{len(q):<5}")

    print("\nHOW TO READ THIS:")
    print("If Q4's avg move is meaningfully larger than Q1's, past volatility DOES")
    print("predict near-term move size in general -- the screener's volatility factor")
    print("is picking up on a real pattern (though NOT proven specific to earnings days).")
    print("If the rows look similar, the factor isn't earning its weight and should be")
    print("reduced or removed from the score.")
    print("\nThis says NOTHING about direction (up vs down) -- magnitude only.")


if __name__ == "__main__":
    main()
