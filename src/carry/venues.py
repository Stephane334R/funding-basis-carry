"""Public REST fetchers for funding rates and prices (no API keys needed).

Every fetcher returns a DataFrame with a common schema:

    funding : ts (UTC datetime of settlement), venue, coin, rate (fraction paid per settlement)
    prices  : ts (UTC datetime, hourly open time), close

Convention for `rate`: positive = longs pay shorts (the standard on all four venues).

Funding intervals differ: Binance / Bybit / OKX settle every 8h for BTC & ETH
(some altcoins every 4h or 1h), Hyperliquid every hour. We never assume the
interval: payments are kept at their real settlement times.

The fetchers follow each venue's public API documentation. Pagination limits
and history depth change over time; the first time you run them, fetch a few
days and inspect the output (`python -m carry.cli fetch --days 3`).
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import pandas as pd
import requests

log = logging.getLogger("venues")
_session = requests.Session()


def _get(url: str, params: dict | None = None, method: str = "GET", json_body: dict | None = None, retries: int = 4):
    for attempt in range(retries):
        try:
            r = _session.request(method, url, params=params, json=json_body, timeout=20)
            if r.status_code == 429:
                raise requests.HTTPError("rate limited")
            r.raise_for_status()
            time.sleep(0.15)  # stay well under public rate limits
            return r.json()
        except (requests.RequestException, ValueError) as exc:
            wait = 2 ** attempt
            log.warning("%s failed (%s), retry in %ss", url, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url} {params or json_body}")


def _ms(ts: pd.Timestamp) -> int:
    return int(pd.Timestamp(ts).timestamp() * 1000)


def _funding_frame(rows: list[tuple[int, float]], venue: str, coin: str) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts_ms", "rate"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["venue"], df["coin"] = venue, coin
    df = df.drop_duplicates("ts_ms").sort_values("ts").reset_index(drop=True)
    return df[["ts", "venue", "coin", "rate"]]


# ----------------------------------------------------------------------------- funding

def binance_funding(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    rows, cursor = [], _ms(start)
    while cursor < _ms(end):
        data = _get(url, {"symbol": f"{coin}USDT", "startTime": cursor, "endTime": _ms(end), "limit": 1000})
        if not data:
            break
        rows += [(int(d["fundingTime"]), float(d["fundingRate"])) for d in data]
        cursor = int(data[-1]["fundingTime"]) + 1
        if len(data) < 1000:
            break
    return _funding_frame(rows, "binance", coin)


def bybit_funding(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Bybit returns newest first; paginate backwards with endTime."""
    url = "https://api.bybit.com/v5/market/funding/history"
    rows, cursor = [], _ms(end)
    while cursor > _ms(start):
        data = _get(url, {"category": "linear", "symbol": f"{coin}USDT", "endTime": cursor, "limit": 200})
        items = (data.get("result") or {}).get("list") or []
        if not items:
            break
        rows += [(int(d["fundingRateTimestamp"]), float(d["fundingRate"])) for d in items]
        oldest = min(int(d["fundingRateTimestamp"]) for d in items)
        if oldest >= cursor:
            break
        cursor = oldest - 1
    df = _funding_frame(rows, "bybit", coin)
    return df[df["ts"] >= pd.Timestamp(start)].reset_index(drop=True)


def okx_funding(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """OKX returns newest first; `after` = return records older than this fundingTime.

    The public endpoint only goes back a few months. For longer history use
    OKX's historical data downloads and drop the files into data/raw/.
    """
    url = "https://www.okx.com/api/v5/public/funding-rate-history"
    rows, after = [], _ms(end)
    while True:
        data = _get(url, {"instId": f"{coin}-USDT-SWAP", "after": after, "limit": 100})
        items = data.get("data") or []
        if not items:
            break
        rows += [(int(d["fundingTime"]), float(d.get("realizedRate") or d["fundingRate"])) for d in items]
        oldest = min(int(d["fundingTime"]) for d in items)
        if oldest <= _ms(start) or oldest >= after:
            break
        after = oldest
    df = _funding_frame(rows, "okx", coin)
    return df[df["ts"] >= pd.Timestamp(start)].reset_index(drop=True)


def hyperliquid_funding(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Hourly funding. Page forward by moving startTime past the last record."""
    url = "https://api.hyperliquid.xyz/info"
    rows, cursor = [], _ms(start)
    while cursor < _ms(end):
        data = _get(url, method="POST", json_body={
            "type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": _ms(end)})
        if not data:
            break
        rows += [(int(d["time"]), float(d["fundingRate"])) for d in data]
        last = int(data[-1]["time"])
        if last < cursor:
            break
        cursor = last + 1
    return _funding_frame(rows, "hyperliquid", coin)


FUNDING_FETCHERS: dict[str, Callable[[str, pd.Timestamp, pd.Timestamp], pd.DataFrame]] = {
    "binance": binance_funding,
    "bybit": bybit_funding,
    "okx": okx_funding,
    "hyperliquid": hyperliquid_funding,
}


# ----------------------------------------------------------------------------- prices

def _binance_klines(url: str, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows, cursor = [], _ms(start)
    while cursor < _ms(end):
        data = _get(url, {"symbol": symbol, "interval": "1h", "startTime": cursor, "endTime": _ms(end), "limit": 1000})
        if not data:
            break
        rows += [(int(k[0]), float(k[4])) for k in data]
        cursor = int(data[-1][0]) + 3_600_000
        if len(data) < 1000:
            break
    df = pd.DataFrame(rows, columns=["ts_ms", "close"]).drop_duplicates("ts_ms")
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["ts", "close"]].sort_values("ts").reset_index(drop=True)


def binance_spot_hourly(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return _binance_klines("https://api.binance.com/api/v3/klines", f"{coin}USDT", start, end)


def binance_perp_hourly(coin: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return _binance_klines("https://fapi.binance.com/fapi/v1/klines", f"{coin}USDT", start, end)
