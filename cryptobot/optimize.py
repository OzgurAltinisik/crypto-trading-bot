"""Parameter search that guards against overfitting.

Walk-forward: the history is cut into consecutive windows. In each window
the best parameters are picked on the *train* part only and then traded on
the following *test* part, which the search never saw. Chaining the test
parts gives an out-of-sample equity curve: an honest estimate of what the
strategy would have done live with periodic re-optimisation.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import pandas as pd
import yaml

from .backtest import run_backtest
from .config import ROOT, BotConfig

EXPERIMENTS = ROOT / "config" / "optimize.yaml"


def expand_grid(base: dict, grid: dict) -> list[dict]:
    keys = list(grid)
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        p = dict(base)
        p.update(zip(keys, values))
        combos.append(p)
    return combos


def score(metrics: dict, min_trades: int) -> float:
    """Selection objective on the train window: annualised Sharpe of the
    equity curve, but only with enough trades to mean anything."""
    if metrics["trades"] < min_trades:
        return -math.inf
    s = metrics["sharpe"]
    return -math.inf if s is None or math.isnan(s) else s


def make_bot(symbol: str, timeframe: str, strategy: str, params: dict, fee: float) -> BotConfig:
    return BotConfig(id=f"{strategy}", symbol=symbol, timeframe=timeframe, strategy_name=strategy,
                     params=params, fee=fee, initial_balance=10_000.0)


@dataclass
class WindowResult:
    train: tuple
    test: tuple
    params: dict
    train_score: float
    test_return_pct: float
    test_buy_hold_pct: float
    test_trades: int
    test_max_dd_pct: float


def grid_search(candles, symbol, timeframe, strategy, combos, start, end, fee, min_trades):
    rows = []
    for p in combos:
        try:
            r = run_backtest(make_bot(symbol, timeframe, strategy, p, fee), start, end, candles=candles)
        except ValueError:
            continue
        m = r.metrics()
        rows.append({"params": p, "score": score(m, min_trades), **m})
    return sorted(rows, key=lambda x: x["score"], reverse=True)


def walk_forward(candles, symbol, timeframe, strategy, combos, start, end=None,
                 train_months=24, test_months=6, fee=0.001, min_trades=8):
    start = pd.Timestamp(start, tz="UTC")
    end = pd.Timestamp(end, tz="UTC") if end else candles.index[-1]
    windows: list[WindowResult] = []
    t0 = start
    while True:
        train_end = t0 + pd.DateOffset(months=train_months)
        test_end = min(train_end + pd.DateOffset(months=test_months), end)
        if train_end >= end:
            break
        ranked = grid_search(candles, symbol, timeframe, strategy, combos, t0, train_end, fee, min_trades)
        best = ranked[0]
        test = run_backtest(make_bot(symbol, timeframe, strategy, best["params"], fee),
                            train_end, test_end, candles=candles)
        tm = test.metrics()
        windows.append(WindowResult(
            train=(t0, train_end), test=(train_end, test_end), params=best["params"],
            train_score=best["score"], test_return_pct=tm["total_return_pct"],
            test_buy_hold_pct=tm["buy_hold_return_pct"], test_trades=tm["trades"],
            test_max_dd_pct=tm["max_drawdown_pct"],
        ))
        t0 = t0 + pd.DateOffset(months=test_months)
        if test_end >= end:
            break
    return windows


def summarize_walk_forward(windows: list[WindowResult], grid_keys: list[str]) -> str:
    if not windows:
        return "No walk-forward windows (history too short)."
    eq = bh = 1.0
    lines = [f"{'test window':<25} {'params':<45} {'OOS ret':>8} {'B&H':>8} {'trades':>6} {'maxDD':>7}"]
    for w in windows:
        eq *= 1 + w.test_return_pct / 100
        bh *= 1 + w.test_buy_hold_pct / 100
        ps = ", ".join(f"{k}={w.params[k]}" for k in grid_keys)
        lines.append(f"{w.test[0]:%Y-%m-%d} → {w.test[1]:%Y-%m-%d}  {ps:<45} "
                     f"{w.test_return_pct:7.1f}% {w.test_buy_hold_pct:7.1f}% {w.test_trades:6d} {w.test_max_dd_pct:6.1f}%")
    worst = min(w.test_max_dd_pct for w in windows)
    pos = sum(w.test_return_pct > 0 for w in windows)
    lines.append(f"\nOut-of-sample compounded: {(eq - 1) * 100:+.1f}%   buy & hold: {(bh - 1) * 100:+.1f}%   "
                 f"positive windows: {pos}/{len(windows)}   worst window DD: {worst:.1f}%")
    return "\n".join(lines)


def load_experiments(path=EXPERIMENTS) -> dict:
    return yaml.safe_load(open(path, encoding="utf-8"))["experiments"]
