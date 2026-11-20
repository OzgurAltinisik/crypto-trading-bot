"""Strategies. The live engine and the backtester both use these classes,
so what is backtested is exactly what runs live.

Every strategy = entry/exit *signals* (strategy-specific) + shared filters
(trend EMA, ADX, RSI) + shared exits (stop, target, break-even, trailing)."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional

import pandas as pd

from . import indicators as ind


@dataclass
class BaseParams:
    # --- filters (all optional) ---
    trend: Optional[int] = None               # only buy while close > EMA(trend)
    trend_slope_lookback: Optional[int] = None  # ...and EMA(trend) rising vs N bars ago
    adx_length: int = 14
    adx_min: Optional[float] = None           # only buy while ADX > this (trending market)
    rsi_length: int = 14
    rsi_smoothing: str = "wilder"             # "wilder" (TradingView) or "ema" (v1 scripts)
    rsi_buy_max: Optional[float] = None       # buy only if RSI < this
    rsi_sell_min: Optional[float] = None      # sell signal only if RSI > this
    # --- exits ---
    atr_length: int = 14
    stop_type: str = "atr"                    # "atr" or "pct"
    stop_value: float = 2.0                   # ATR multiple, or fraction (0.08 = 8%)
    take_profit_atr: Optional[float] = None   # ATR multiple; None = no fixed target
    breakeven_at: Optional[float] = None      # fraction of entry->target distance
    trail_atr: Optional[float] = None         # trailing stop: highest high - ATR(entry) * this

    @classmethod
    def from_dict(cls, d: dict):
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"Unknown strategy params: {sorted(unknown)}")
        p = cls(**d)
        p.validate()
        return p

    def validate(self):
        if self.rsi_smoothing not in ("wilder", "ema"):
            raise ValueError("rsi_smoothing must be 'wilder' or 'ema'")
        if self.stop_type not in ("atr", "pct"):
            raise ValueError("stop_type must be 'atr' or 'pct'")
        if self.breakeven_at is not None and self.take_profit_atr is None:
            raise ValueError("breakeven_at needs take_profit_atr")


@dataclass
class EmaCrossParams(BaseParams):
    fast: int = 9
    slow: int = 21


@dataclass
class DonchianParams(BaseParams):
    entry_period: int = 20   # buy when close breaks the highest high of the last N bars
    exit_period: int = 10    # sell signal when close breaks the lowest low of the last M bars


@dataclass
class Levels:
    stop: float
    take_profit: Optional[float]
    breakeven_trigger: Optional[float]
    trail_distance: Optional[float] = None


class BaseStrategy:
    name = "base"
    params_cls = BaseParams

    def __init__(self, params: BaseParams):
        self.p = params

    # subclasses: return (raw_buy, raw_sell) boolean Series and the longest lookback
    def entry_exit(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        raise NotImplementedError

    def own_lookback(self) -> int:
        raise NotImplementedError

    @property
    def warmup_bars(self) -> int:
        """Bars needed before the slowest EMA has converged (~4x its length)."""
        longest = max(self.own_lookback(), self.p.trend or 0, self.p.adx_length * 2)
        return longest * 4 + (self.p.trend_slope_lookback or 0)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add indicator columns plus boolean `buy` / `sell` columns.
        Every value at row i depends only on rows <= i (no look-ahead)."""
        p = self.p
        df = df.copy()
        df["rsi"] = ind.rsi(df["close"], p.rsi_length, p.rsi_smoothing)
        df["atr"] = ind.atr(df, p.atr_length)
        buy, sell = self.entry_exit(df)

        if p.trend:
            df["ema_trend"] = ind.ema(df["close"], p.trend)
            buy &= df["close"] > df["ema_trend"]
            if p.trend_slope_lookback:
                buy &= df["ema_trend"] > df["ema_trend"].shift(p.trend_slope_lookback)
        if p.adx_min is not None:
            df["adx"] = ind.adx(df, p.adx_length)
            buy &= df["adx"] > p.adx_min
        if p.rsi_buy_max is not None:
            buy &= df["rsi"] < p.rsi_buy_max
        if p.rsi_sell_min is not None:
            sell &= df["rsi"] > p.rsi_sell_min

        df["buy"] = buy.fillna(False).astype(bool)
        df["sell"] = sell.fillna(False).astype(bool)
        return df

    def levels(self, entry: float, row) -> Levels:
        """Stop, target, break-even trigger and trailing distance for a new position."""
        p = self.p
        a = float(row["atr"])
        stop = entry - a * p.stop_value if p.stop_type == "atr" else entry * (1 - p.stop_value)
        tp = entry + a * p.take_profit_atr if p.take_profit_atr else None
        be = entry + (tp - entry) * p.breakeven_at if (p.breakeven_at is not None and tp) else None
        trail = a * p.trail_atr if p.trail_atr else None
        return Levels(stop=stop, take_profit=tp, breakeven_trigger=be, trail_distance=trail)

    def describe_entry(self) -> str:
        raise NotImplementedError

    def describe(self) -> str:
        p = self.p
        parts = [self.describe_entry()]
        if p.trend:
            parts.append(f"trend EMA{p.trend}" + (" + slope" if p.trend_slope_lookback else ""))
        if p.adx_min is not None:
            parts.append(f"ADX>{p.adx_min:g}")
        if p.rsi_buy_max is not None:
            parts.append(f"RSI<{p.rsi_buy_max:g}")
        parts.append(f"SL ATR×{p.stop_value:g}" if p.stop_type == "atr" else f"SL {p.stop_value * 100:g}%")
        if p.take_profit_atr:
            parts.append(f"TP ATR×{p.take_profit_atr:g}")
        if p.breakeven_at is not None:
            parts.append(f"BE at {p.breakeven_at:g}")
        if p.trail_atr:
            parts.append(f"trail ATR×{p.trail_atr:g}")
        return " · ".join(parts)


class EmaCrossStrategy(BaseStrategy):
    """Buy when the fast EMA crosses above the slow one; sell signal on the cross down."""

    name = "ema_cross"
    params_cls = EmaCrossParams

    def entry_exit(self, df):
        p = self.p
        df["ema_fast"] = ind.ema(df["close"], p.fast)
        df["ema_slow"] = ind.ema(df["close"], p.slow)
        f, s = df["ema_fast"], df["ema_slow"]
        buy = (f > s) & (f.shift(1) <= s.shift(1))
        sell = (f < s) & (f.shift(1) >= s.shift(1))
        return buy, sell

    def own_lookback(self):
        return self.p.slow

    def describe_entry(self):
        return f"EMA {self.p.fast}/{self.p.slow}"


class DonchianStrategy(BaseStrategy):
    """Channel breakout (classic trend following): buy when the close exceeds
    the highest high of the previous N bars, sell signal when it falls below
    the lowest low of the previous M bars."""

    name = "donchian"
    params_cls = DonchianParams

    def entry_exit(self, df):
        p = self.p
        df["dc_high"] = df["high"].rolling(p.entry_period).max().shift(1)
        df["dc_low"] = df["low"].rolling(p.exit_period).min().shift(1)
        above = df["close"] > df["dc_high"]
        buy = above & ~above.shift(1, fill_value=False)   # first close above the channel
        sell = df["close"] < df["dc_low"]
        return buy, sell

    def own_lookback(self):
        return max(self.p.entry_period, self.p.exit_period)

    def describe_entry(self):
        return f"Donchian {self.p.entry_period}/{self.p.exit_period}"


STRATEGIES = {s.name: s for s in (EmaCrossStrategy, DonchianStrategy)}


def build_strategy(name: str, params: dict):
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGIES)}")
    cls = STRATEGIES[name]
    return cls(cls.params_cls.from_dict(params or {}))
