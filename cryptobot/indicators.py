"""Technical indicators, computed the same way TradingView does."""
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponential moving average (TradingView `ta.ema`)."""
    return series.ewm(span=length, adjust=False).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average (TradingView `ta.rma`), used by RSI and ATR."""
    return series.ewm(alpha=1 / length, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14, smoothing: str = "wilder") -> pd.Series:
    """RSI. `wilder` matches TradingView `ta.rsi`; `ema` (span=length) is what
    the original v1 scripts used and reacts faster."""
    delta = close.diff()
    if smoothing == "wilder":
        avg = rma
    elif smoothing == "ema":
        avg = ema
    else:
        raise ValueError("smoothing must be 'wilder' or 'ema'")
    gain = avg(delta.clip(lower=0), length)
    loss = avg(-delta.clip(upper=0), length)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    # No losses in the window -> RSI 100; no movement at all -> 50.
    out = out.where(loss != 0, 100.0)
    out = out.where((gain != 0) | (loss != 0), 50.0)
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average true range (TradingView `ta.atr`)."""
    return rma(true_range(df), length)


def adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Wilder's ADX (TradingView `ta.dmi` ADX). Trend strength 0-100,
    direction-agnostic; below ~20 usually means a choppy, range-bound market."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = rma(true_range(df), length)
    plus_di = 100 * rma(plus_dm, length) / tr
    minus_di = 100 * rma(minus_dm, length) / tr
    di_sum = (plus_di + minus_di).replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return rma(dx.fillna(0), length)
