"""XAUUSD-only TickFeed market-data adapter (read-only).

Uses TickFeed's documented REST endpoints for XAUUSD only. No crypto,
other forex symbols, order routing, synthetic candles, or gap filling.
Gold OTC volume is provider tick-volume, not centralized exchange volume.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any

import requests

from market_models import Candle

BASE_URL = os.getenv("TICKFEED_BASE_URL", "https://api.tickfeed.pro").rstrip("/")
SYMBOL = "XAUUSD"
TIMEFRAMES = {
    "1m": ("M1", 60_000),
    "5m": ("M5", 300_000),
    "15m": ("M15", 900_000),
    "1h": ("H1", 3_600_000),
    "4h": ("H4", 14_400_000),
    "1d": ("D1", 86_400_000),
}


class TickFeedError(RuntimeError):
    """Raised when TickFeed data is unavailable or invalid."""


def _headers() -> dict[str, str]:
    key = os.getenv("TICKFEED_API_KEY", "mdp_XDcYsH").strip()
    return {"X-API-Key":mdp_XDcYsH} if key else {}


def _get(path: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict:
    try:
        response = requests.get(
            f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=timeout
        )
        if not response.ok:
            raise TickFeedError(f"TickFeed HTTP {response.status_code}: {response.text[:240]}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise TickFeedError("TickFeed returned a non-object response")
        return payload
    except requests.RequestException as exc:
        raise TickFeedError(f"TickFeed connection failed: {exc}") from exc
    except ValueError as exc:
        raise TickFeedError("TickFeed returned invalid JSON") from exc


def _assert_xauusd(payload: dict) -> None:
    # The endpoint path is fixed to XAUUSD. If the provider includes a symbol,
    # verify it rather than silently accepting another instrument.
    symbol = payload.get("symbol")
    if symbol is not None and str(symbol).upper() != SYMBOL:
        raise TickFeedError(f"Unexpected instrument in TickFeed response: {symbol}")


def fetch_xauusd_price() -> dict:
    """Return the XAUUSD bid/ask quote and its freshness metadata."""
    data = _get(f"/v1/price/{SYMBOL}")
    _assert_xauusd(data)
    required = ("bid", "ask", "tick_time", "freshness")
    if any(k not in data for k in required):
        raise TickFeedError("TickFeed XAUUSD price response is missing required fields")
    try:
        bid, ask = float(data["bid"]), float(data["ask"])
    except (TypeError, ValueError) as exc:
        raise TickFeedError("TickFeed returned a non-numeric XAUUSD quote") from exc
    if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid <= ask):
        raise TickFeedError("TickFeed returned an invalid XAUUSD bid/ask")
    # Preserve freshness exactly. Callers must not treat stale/closed quotes as live.
    return {**data, "symbol": SYMBOL, "bid": bid, "ask": ask,
            "mid": (bid + ask) / 2, "spread": ask - bid}


def fetch_feed_health() -> dict:
    """Return provider health; this endpoint is public and requires no API key."""
    return _get("/health")


def fetch_xauusd_gaps(interval: str = "5m", start_time: str | None = None,
                       end_time: str | None = None) -> dict:
    """Return TickFeed's reported XAUUSD history gaps; never fills gaps."""
    timeframe = TIMEFRAMES.get(interval.lower())
    if timeframe is None:
        raise ValueError(f"Unsupported interval {interval}; use {', '.join(TIMEFRAMES)}")
    params: dict[str, str] = {"timeframe": timeframe[0]}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    payload = _get(f"/v1/candles/{SYMBOL}/gaps", params)
    _assert_xauusd(payload)
    return payload


def fetch_xauusd_klines(interval: str = "5m", limit: int = 500,
                         source: str = "live") -> list[Candle]:
    """Fetch completed XAUUSD candles, oldest first, without inventing missing bars."""
    timeframe = TIMEFRAMES.get(interval.lower())
    if timeframe is None:
        raise ValueError(f"Unsupported interval {interval}; use {', '.join(TIMEFRAMES)}")
    tf, duration_ms = timeframe
    if isinstance(limit, bool) or not 1 <= int(limit) <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if source not in {"live", "stored"}:
        raise ValueError("source must be 'live' or 'stored'")

    payload = _get(
        f"/v1/candles/{SYMBOL}",
        {"timeframe": tf, "limit": int(limit), "source": source},
    )
    _assert_xauusd(payload)
    raw = payload.get("candles")
    if not isinstance(raw, list):
        raise TickFeedError("TickFeed XAUUSD response does not contain a candles list")

    by_time: dict[int, Candle] = {}
    for row in raw:
        if not isinstance(row, dict) or row.get("complete") is False:
            continue
        stamp = row.get("time")
        if not isinstance(stamp, str):
            continue
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            open_ms = int(dt.timestamp() * 1000)
            o, h, l, c = (float(row[k]) for k in ("open", "high", "low", "close"))
            # TickFeed's documented candle field is tick_volume. Do not substitute
            # centralized volume or fabricate volume when it is absent.
            if "tick_volume" not in row:
                raise TickFeedError("XAUUSD candle is missing tick_volume required by FRVP")
            vol = float(row["tick_volume"])
        except TickFeedError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        values = (o, h, l, c, vol)
        if not all(math.isfinite(v) for v in values):
            continue
        if min(o, h, l, c) <= 0 or vol < 0 or h < max(o, c, l) or l > min(o, c, h):
            continue
        by_time[open_ms] = Candle(
            open_time=open_ms, open=o, high=h, low=l, close=c,
            volume=vol, close_time=open_ms + duration_ms - 1,
            quote_volume=0.0, trades=0,
            taker_buy_base=0.0, taker_buy_quote=0.0,
        )

    result = [by_time[t] for t in sorted(by_time)]
    if not result:
        raise TickFeedError(f"TickFeed returned no valid completed XAUUSD {tf} candles")
    if len(result) < int(limit):
        # The provider may return fewer bars at the edge of available history or
        # around closures. Report the actual count; never synthesize missing bars.
        pass
    return result[-int(limit):]
