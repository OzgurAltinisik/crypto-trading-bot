"""Market data from Binance's public API (no API key needed)."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import ccxt
import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def make_exchange(name: str = "binance") -> ccxt.Exchange:
    return getattr(ccxt, name)({"enableRateLimit": True})


def timeframe_ms(timeframe: str) -> int:
    return ccxt.Exchange.parse_timeframe(timeframe) * 1000


def to_frame(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def drop_open_candle(df: pd.DataFrame, timeframe: str, now_ms: int) -> pd.DataFrame:
    """Remove the last candle if it has not closed yet.

    Signals must only be computed from closed candles; the forming candle
    changes every second and would make signals appear and disappear."""
    if df.empty:
        return df
    last_open_ms = int(df.index[-1].timestamp() * 1000)
    if last_open_ms + timeframe_ms(timeframe) > now_ms:
        return df.iloc[:-1]
    return df


def with_retry(fn, *args, attempts: int = 4, base_delay: float = 2.0, **kwargs):
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
            if i == attempts - 1:
                raise
            delay = base_delay * 2**i
            log.warning("Network error (%s), retrying in %.0fs", e, delay)
            time.sleep(delay)


def fetch_closed_candles(
    exchange: ccxt.Exchange, symbol: str, timeframe: str, limit: int = 1000
) -> pd.DataFrame:
    """Latest `limit` candles, closed ones only."""
    rows = with_retry(exchange.fetch_ohlcv, symbol, timeframe, limit=limit)
    return drop_open_candle(to_frame(rows), timeframe, exchange.milliseconds())


def fetch_history(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since: pd.Timestamp,
    until: Optional[pd.Timestamp] = None,
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """All closed candles from `since` to `until` (default: now), paginated.

    With `cache_dir`, candles are stored as CSV and only missing ones fetched."""
    since = pd.Timestamp(since, tz="UTC") if since.tzinfo is None else since
    cached = pd.DataFrame()
    cache_file = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{exchange.id}_{symbol.replace('/', '')}_{timeframe}.csv"
        if cache_file.exists():
            cached = pd.read_csv(cache_file, index_col="timestamp", parse_dates=True)
            if cached.index.tz is None:
                cached.index = cached.index.tz_localize("UTC")

    tf_ms = timeframe_ms(timeframe)
    rows: list = []
    # Fetch what is before and after the cached range.
    ranges = []
    if cached.empty:
        ranges.append(int(since.timestamp() * 1000))
    else:
        if since < cached.index[0]:
            ranges.append(int(since.timestamp() * 1000))
        ranges.append(int(cached.index[-1].timestamp() * 1000) + tf_ms)

    for start in ranges:
        cursor = start
        stop_at = int(cached.index[0].timestamp() * 1000) if (not cached.empty and start < cached.index[0].timestamp() * 1000) else None
        while True:
            batch = with_retry(exchange.fetch_ohlcv, symbol, timeframe, since=cursor, limit=1000)
            if not batch:
                break
            rows += batch
            cursor = batch[-1][0] + tf_ms
            if len(batch) < 1000 or (stop_at and cursor >= stop_at):
                break

    df = to_frame(rows) if rows else pd.DataFrame(columns=COLUMNS[1:])
    if not cached.empty:
        df = pd.concat([cached, df])
        df = df[~df.index.duplicated(keep="last")].sort_index()
    df = drop_open_candle(df, timeframe, exchange.milliseconds())

    if cache_file is not None and not df.empty:
        df.to_csv(cache_file, index_label="timestamp")

    df = df[df.index >= since]
    if until is not None:
        until = pd.Timestamp(until, tz="UTC") if until.tzinfo is None else until
        df = df[df.index <= until]
    return df
