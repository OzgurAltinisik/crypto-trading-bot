"""Backtester: replays history through the same strategy and PaperAccount
the live engine uses."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from .account import PaperAccount, Trade
from .config import BotConfig
from .data import fetch_history, make_exchange, timeframe_ms


@dataclass
class BacktestResult:
    bot_id: str
    start: pd.Timestamp
    end: pd.Timestamp
    trades: list[Trade]
    equity: pd.Series        # marked-to-market balance per bar
    prices: pd.DataFrame     # prepared candles (indicators + signals)
    initial_balance: float

    def metrics(self) -> dict:
        eq = self.equity
        n = len(self.trades)
        pnl = pd.Series([t.pnl_pct for t in self.trades], dtype=float)
        wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
        gross_win = sum(t.pnl_usd for t in self.trades if t.pnl_usd > 0)
        gross_loss = -sum(t.pnl_usd for t in self.trades if t.pnl_usd <= 0)

        drawdown = eq / eq.cummax() - 1
        first, last = self.prices["close"].iloc[0], self.prices["close"].iloc[-1]

        rets = eq.pct_change().dropna()
        bars_per_year = 365 * 24 * 3600 * 1000 / self._tf_ms()
        sharpe = (rets.mean() / rets.std() * math.sqrt(bars_per_year)) if rets.std() > 0 else float("nan")
        years = (self.end - self.start).total_seconds() / (365 * 24 * 3600)
        total = eq.iloc[-1] / self.initial_balance - 1
        cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan")

        in_pos = self.prices.get("in_position")
        return {
            "period": f"{self.start:%Y-%m-%d} → {self.end:%Y-%m-%d}",
            "total_return_pct": total * 100,
            "buy_hold_return_pct": (last / first - 1) * 100,
            "cagr_pct": cagr * 100,
            "max_drawdown_pct": drawdown.min() * 100,
            "buy_hold_max_drawdown_pct": (self.prices["close"] / self.prices["close"].cummax() - 1).min() * 100,
            "sharpe": sharpe,
            "trades": n,
            "win_rate_pct": len(wins) / n * 100 if n else float("nan"),
            "avg_win_pct": wins.mean() if len(wins) else float("nan"),
            "avg_loss_pct": losses.mean() if len(losses) else float("nan"),
            "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("inf"),
            "exposure_pct": in_pos.mean() * 100 if in_pos is not None else float("nan"),
            "avg_position_pct": (sum(t.position_pct or 0 for t in self.trades) / n) if n else float("nan"),
            "exit_reasons": pd.Series([t.reason for t in self.trades]).value_counts().to_dict(),
        }

    def _tf_ms(self) -> int:
        idx = self.prices.index
        return int((idx[1] - idx[0]).total_seconds() * 1000) if len(idx) > 1 else 3_600_000

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(t) for t in self.trades])


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def run_backtest(
    bot: BotConfig,
    start,
    end=None,
    cache_dir=None,
    candles: pd.DataFrame | None = None,
) -> BacktestResult:
    """Fetch candles (plus warm-up history before `start`) and replay them."""
    start_ts = _utc(start)
    end_ts = _utc(end) if end is not None else None
    strat = bot.strategy
    if candles is None:
        warmup_start = start_ts - pd.Timedelta(milliseconds=timeframe_ms(bot.timeframe) * strat.warmup_bars)
        candles = fetch_history(make_exchange(), bot.symbol, bot.timeframe, warmup_start, end_ts, cache_dir)

    df = strat.prepare(candles)
    df = df[df.index >= start_ts]
    if end_ts is not None:
        df = df[df.index <= end_ts]
    if df.empty:
        raise ValueError("No candles in the requested period")

    acc = PaperAccount(strat, bot.fee, bot.initial_balance, sizing=bot.sizing)
    trades: list[Trade] = []
    equity, in_position = [], []
    # plain dicts are ~20x faster to iterate than DataFrame.iterrows()
    for t, row in zip(df.index, df.to_dict("records")):
        for e in acc.on_bar(t, row):
            if e.kind == "close":
                trades.append(e.trade)
        # mark to market at the close (what the balance would be if sold now)
        equity.append(acc.equity(row["close"]))
        in_position.append(acc.position is not None)

    df = df.assign(in_position=in_position)
    return BacktestResult(
        bot_id=bot.id,
        start=df.index[0],
        end=df.index[-1],
        trades=trades,
        equity=pd.Series(equity, index=df.index, name="equity"),
        prices=df,
        initial_balance=bot.initial_balance,
    )


def format_report(r: BacktestResult) -> str:
    m = r.metrics()

    def f(v, suffix="", digits=2):
        return "n/a" if isinstance(v, float) and math.isnan(v) else f"{v:,.{digits}f}{suffix}"

    lines = [
        f"===== {r.bot_id} =====",
        f"Period            : {m['period']}",
        f"Total return      : {f(m['total_return_pct'], '%')}   (buy & hold: {f(m['buy_hold_return_pct'], '%')})",
        f"CAGR              : {f(m['cagr_pct'], '%')}",
        f"Max drawdown      : {f(m['max_drawdown_pct'], '%')}   (buy & hold: {f(m['buy_hold_max_drawdown_pct'], '%')})",
        f"Sharpe (annual)   : {f(m['sharpe'])}",
        f"Trades            : {m['trades']}",
        f"Win rate          : {f(m['win_rate_pct'], '%', 1)}",
        f"Avg win / loss    : {f(m['avg_win_pct'], '%')} / {f(m['avg_loss_pct'], '%')}",
        f"Profit factor     : {f(m['profit_factor'])}",
        f"Time in market    : {f(m['exposure_pct'], '%', 1)}",
        f"Avg position size : {f(m['avg_position_pct'], '% of balance', 0)}",
        f"Exit reasons      : {m['exit_reasons']}",
    ]
    if m["trades"] < 30:
        lines.append("⚠️  Fewer than 30 trades: results are not statistically reliable.")
    return "\n".join(lines)


def plot(r: BacktestResult, path=None) -> None:
    import matplotlib.pyplot as plt

    df = r.prices
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 9), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
    ax1.plot(df.index, df["close"], lw=0.8, label="Close", color="#444")
    ax1.plot(df.index, df["ema_fast"], lw=1, label="EMA fast")
    ax1.plot(df.index, df["ema_slow"], lw=1, label="EMA slow")
    if "ema_trend" in df:
        ax1.plot(df.index, df["ema_trend"], lw=1, label="EMA trend")
    for t in r.trades:
        et, xt = pd.Timestamp(t.entry_time), pd.Timestamp(t.exit_time)
        ax1.scatter(et, t.entry_price, marker="^", color="green", s=50, zorder=5)
        ax1.scatter(xt, t.exit_price, marker="v", color="green" if t.pnl_pct > 0 else "red", s=50, zorder=5)
    ax1.set_title(f"{r.bot_id} — {r.start:%Y-%m-%d} → {r.end:%Y-%m-%d}")
    ax1.legend(loc="upper left", fontsize=8)

    bh = r.initial_balance * df["close"] / df["close"].iloc[0]
    ax2.plot(r.equity.index, r.equity, label="Strategy", color="goldenrod")
    ax2.plot(bh.index, bh, label="Buy & hold", color="gray", lw=0.8)
    ax2.axhline(r.initial_balance, color="gray", ls="--", lw=0.6)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.set_ylabel("Balance ($)")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=110)
    else:
        plt.show()
