"""
Shared helpers for talking to the Financial Modeling Prep `stable` API.
Used by both screener.py and backtest.py so there's one source of truth
for how requests are made, rate-limited, and errors are handled.
"""

import os
import sys
import time
import json
from urllib import request, parse, error

FMP_BASE = "https://financialmodelingprep.com/stable"
REQUEST_PAUSE_SEC = 0.25  # be polite to the free-tier rate limit


def api_get(path, params=None):
    """GET a FMP `stable` endpoint. Returns parsed JSON or None on failure."""
    key = os.environ.get("FMP_API_KEY")
    if not key:
        sys.exit("ERROR: set FMP_API_KEY environment variable first.")
    params = dict(params or {})
    params["apikey"] = key
    url = f"{FMP_BASE}/{path}?{parse.urlencode(params)}"
    try:
        with request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        print(f"  [warn] HTTP {e.code} for {path} ({params.get('symbol', '')})", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [warn] request failed for {path}: {e}", file=sys.stderr)
        return None
    finally:
        time.sleep(REQUEST_PAUSE_SEC)


def get_price_history(symbol, start_iso, end_iso):
    """Returns a list of {date, close} dicts sorted ascending by date, or None."""
    data = api_get("historical-price-eod/full", {
        "symbol": symbol,
        "from": start_iso,
        "to": end_iso,
    })
    if not data:
        return None
    prices = data.get("historical") if isinstance(data, dict) else data
    if not prices:
        return None
    return sorted(prices, key=lambda r: r["date"])


def get_current_price(symbol):
    """Current price via the /quote endpoint (confirmed free tier)."""
    data = api_get("quote", {"symbol": symbol})
    if not data or not isinstance(data, list) or not data:
        return None
    return data[0].get("price")


# Note: FMP's news/stock-latest endpoint returned HTTP 402 (paywalled) in a
# live test, so headlines are now sourced from Finnhub instead -- see
# finnhub_common.py. Left out of this file to avoid a second dead-end helper.
