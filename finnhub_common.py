"""
Finnhub helper -- used ONLY for headlines, since FMP's news endpoint
returned HTTP 402 (paywalled) in a live test. Finnhub's free tier
(60 calls/minute, no card required) includes company-specific news,
confirmed across multiple independent developer sources.

Get a free key at: https://finnhub.io/register
"""

import os
import sys
from datetime import date, timedelta
from urllib import request, parse, error
import json
import time

FINNHUB_BASE = "https://finnhub.io/api/v1"


def get_finnhub_headlines(symbol, limit=2, days_back=7):
    """
    Best-effort recent headlines for a symbol via Finnhub's free
    company-news endpoint. Returns [] on any failure (missing key,
    rate limit, network issue) -- headlines are a nice-to-have, never
    something the rest of the pipeline depends on.
    """
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        return []  # silently skip if not configured -- not a hard requirement

    end = date.today()
    start = end - timedelta(days=days_back)
    params = {
        "symbol": symbol,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "token": key,
    }
    url = f"{FINNHUB_BASE}/company-news?{parse.urlencode(params)}"
    try:
        with request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, list):
            return []
        # Sort newest first, take the top `limit`
        data.sort(key=lambda item: item.get("datetime", 0), reverse=True)
        return [
            {"title": item.get("headline", "").strip(), "url": item.get("url", "")}
            for item in data[:limit]
            if item.get("headline")
        ]
    except error.HTTPError as e:
        print(f"  [warn] Finnhub HTTP {e.code} for {symbol}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [warn] Finnhub request failed for {symbol}: {e}", file=sys.stderr)
        return []
    finally:
        time.sleep(0.15)  # stay well under 60 calls/min
