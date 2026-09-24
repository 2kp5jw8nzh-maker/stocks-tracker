#!/usr/bin/env python3
"""
Track-Record Checker
=====================

WHAT THIS DOES
--------------
Reads history.csv (built up weekly by screener.py), finds picks that were
flagged at least MIN_AGE_DAYS ago and haven't been checked yet, fetches
their CURRENT price, and fills in what actually happened.

This is the honest way to find out whether a high score means anything in
practice: not a one-time backtest, but a running, ever-growing record of
YOUR OWN screener's actual picks versus actual outcomes. Run it weekly,
right after screener.py (the included GitHub Actions workflow does this
automatically).

IMPORTANT FRAMING
------------------
This logs MAGNITUDE and DIRECTION of what happened -- it does not, and
never will, retroactively prove the score "worked," because a single
stock going up after being flagged could be luck, market-wide movement,
or the actual factors the score measures. Only after many resolved picks
accumulate does the summary stats section start being informative -- and
even then, "informative" means "worth factoring into how much you trust
the score," not "proof of a working strategy."

USAGE
-----
    export FMP_API_KEY="your_key_here"
    python3 track_outcomes.py
"""

import os
import csv
import sys
import statistics
from datetime import date, datetime

from fmp_common import get_current_price

MIN_AGE_DAYS = 28  # roughly a month -- matches the "hold for a month" horizon


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    history_path = os.path.join(base_dir, "history.csv")

    if not os.path.exists(history_path):
        print("No history.csv yet -- run screener.py at least once first.")
        return

    with open(history_path, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("history.csv is empty -- nothing to check yet.")
        return

    today = date.today()
    checked_this_run = 0

    for row in rows:
        if row.get("outcome_pct"):
            continue  # already resolved
        if not row.get("price_at_flag"):
            continue  # price wasn't available when flagged, can't compute a move
        try:
            flagged = datetime.fromisoformat(row["run_date"]).date()
        except ValueError:
            continue
        age_days = (today - flagged).days
        if age_days < MIN_AGE_DAYS:
            continue  # not old enough yet

        current_price = get_current_price(row["symbol"])
        if current_price is None:
            continue  # couldn't fetch -- try again next run

        try:
            price_then = float(row["price_at_flag"])
            pct_move = (current_price - price_then) / price_then * 100
        except (ValueError, ZeroDivisionError):
            continue

        row["outcome_pct"] = round(pct_move, 2)
        row["outcome_checked_date"] = today.isoformat()
        checked_this_run += 1

    # Write the updated file back (full rewrite, since we're editing in place)
    fieldnames = ["run_date", "symbol", "earnings_date", "score", "price_at_flag",
                  "outcome_pct", "outcome_checked_date"]
    with open(history_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Checked {checked_this_run} newly-eligible pick(s) this run.")

    # Summary stats over EVERYTHING resolved so far -- the actual track record
    resolved = [r for r in rows if r.get("outcome_pct") not in (None, "")]
    if not resolved:
        print("No resolved picks yet -- check back after picks age past "
              f"{MIN_AGE_DAYS} days.")
        return

    moves = [float(r["outcome_pct"]) for r in resolved]
    up_count = sum(1 for m in moves if m > 0)
    down_count = sum(1 for m in moves if m < 0)

    print("\n" + "=" * 60)
    print(f"TRACK RECORD SO FAR -- {len(resolved)} resolved pick(s)")
    print("=" * 60)
    print(f"Average move (signed):     {statistics.mean(moves):+.2f}%")
    print(f"Average move (magnitude):  {statistics.mean(abs(m) for m in moves):.2f}%")
    print(f"Up: {up_count}   Down: {down_count}   "
          f"({up_count / len(resolved) * 100:.0f}% were positive)")
    print("\nThis is descriptive, not predictive. A ~50/50 up/down split over")
    print("a small sample tells you almost nothing yet -- keep this running")
    print("for months before drawing any real conclusion.")


if __name__ == "__main__":
    main()
