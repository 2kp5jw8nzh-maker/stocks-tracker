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


def get_recent_headlines(symbol, limit=2):
    """
    Best-effort recent headlines for a symbol. FMP's exact free-tier status
    for news endpoints is unconfirmed (unlike quote/profile/historical-price,
    which are documented free) -- so this fails SILENTLY and returns an
    empty list on any error, rather than treating a missing endpoint as a
    breaking failure. Headlines are a nice-to-have context add, never
    something the rest of the pipeline depends on.
    """
    try:
        data = api_get("news/stock-latest", {"symbols": symbol, "limit": limit})
        if not data or not isinstance(data, list):
            return []
        return [
            {"title": item.get("title", "").strip(), "url": item.get("url", "")}
            for item in data[:limit]
            if item.get("title")
        ]
    except Exception:
        return []
