"""Live engine against a fake exchange: closed candles only, restart
persistence, and catching stops that were hit while offline."""
import numpy as np
import pytest
import pandas as pd

from cryptobot.account import Sizing
from cryptobot.config import BotConfig
from cryptobot.engine import LiveBot
from cryptobot.notifier import TelegramNotifier
from cryptobot.storage import Storage

HOUR = 3_600_000


class FakeExchange:
    def __init__(self, rows):
        self.rows = rows          # [ts, o, h, l, c, v]
        self.now = rows[-1][0] + HOUR + 10_000
        self.price = rows[-1][4]

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, symbol, timeframe, limit=1000, since=None):
        visible = [r for r in self.rows if r[0] <= self.now]   # incl. the forming candle
        return visible[-limit:]

    def fetch_ticker(self, symbol):
        return {"last": self.price}


def rows_from(closes, start_ms=1_735_689_600_000):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append([start_ms + i * HOUR, prev, max(prev, c) + 0.5, min(prev, c) - 0.5, c, 1.0])
        prev = c
    return out


def bot_cfg(**params):
    base = {"fast": 3, "slow": 8, "stop_type": "pct", "stop_value": 0.05}
    base.update(params)
    return BotConfig(id="t", symbol="X/USDT", timeframe="1h", strategy_name="ema_cross", params=base,
                     initial_balance=1000.0, fee=0.0)


def crossing_series():
    # down-trend then a sharp turn up -> fast EMA crosses above slow on the last bar
    return list(np.linspace(120, 100, 40)) + [107.0]


def test_opens_on_closed_candle_and_survives_restart(tmp_path):
    rows = rows_from(crossing_series())
    ex = FakeExchange(rows)
    storage = Storage(tmp_path / "bot.db")
    notifier = TelegramNotifier(None, None)

    bot = LiveBot(bot_cfg(), ex, storage, notifier)
    bot.tick()
    assert bot.account.position is not None
    entry = bot.account.position.entry_price
    assert entry == 107.0

    # restart: a new LiveBot reads the same DB
    bot2 = LiveBot(bot_cfg(), ex, storage, notifier)
    assert bot2.account.position is not None and bot2.account.position.entry_price == entry
    assert bot2.last_candle == bot.last_candle


def test_forming_candle_is_ignored(tmp_path):
    closes = crossing_series()
    rows = rows_from(closes)
    ex = FakeExchange(rows)
    ex.now = rows[-1][0] + 60_000     # last candle is still forming -> no cross yet
    bot = LiveBot(bot_cfg(), ex, Storage(tmp_path / "bot.db"), TelegramNotifier(None, None))
    bot.tick()
    assert bot.account.position is None


def test_stop_hit_while_offline_is_caught(tmp_path):
    rows = rows_from(crossing_series())
    ex = FakeExchange(rows)
    storage = Storage(tmp_path / "bot.db")
    bot = LiveBot(bot_cfg(), ex, storage, TelegramNotifier(None, None))
    bot.tick()
    stop = bot.account.position.stop

    # engine is "offline" for 3 hours; a wick went through the stop and recovered
    last_ts = rows[-1][0]
    rows += [
        [last_ts + HOUR, 107, 108, 106.5, 107, 1],
        [last_ts + 2 * HOUR, 107, 107.5, stop - 2, 106.8, 1],
        [last_ts + 3 * HOUR, 106.8, 107.2, 106.5, 107, 1],
    ]
    ex.now = last_ts + 4 * HOUR + 10_000
    ex.price = 107
    bot2 = LiveBot(bot_cfg(), ex, storage, TelegramNotifier(None, None))
    bot2.tick()
    assert bot2.account.position is None
    with storage._conn() as c:
        t = c.execute("SELECT reason, exit_price FROM trades").fetchone()
    assert t["reason"] == "STOP-LOSS" and t["exit_price"] == stop


@pytest.mark.parametrize("strategy,params", [
    ("ema_cross", dict(take_profit_atr=3.0, stop_type="atr", stop_value=1.5, breakeven_at=0.5)),
    ("donchian", dict(entry_period=10, exit_period=5, stop_type="atr", stop_value=2.0, trail_atr=2.0, adx_min=10)),
])
def test_backtest_and_live_agree(tmp_path, strategy, params):
    """Feeding candles one by one to the live bot gives the same trades as the backtest."""
    from cryptobot.backtest import run_backtest
    from cryptobot.data import to_frame

    rng = np.random.default_rng(7)
    closes = list(rng.normal(0, 1, 400).cumsum() + 200)
    rows = rows_from(closes)
    if strategy == "ema_cross":
        cfg = bot_cfg(**params)
    else:
        cfg = BotConfig(id="t", symbol="X/USDT", timeframe="1h", strategy_name="donchian", params=params,
                        initial_balance=1000.0, fee=0.0, sizing=Sizing(risk_per_trade=0.02))

    bt = run_backtest(cfg, "2025-01-01", candles=to_frame(rows))

    ex = FakeExchange(rows[:30])
    bot = LiveBot(cfg, ex, Storage(tmp_path / "bot.db"), TelegramNotifier(None, None))
    for i in range(30, len(rows) + 1):
        ex.rows = rows[:i]
        ex.now = rows[i - 1][0] + HOUR + 10_000
        bot.process_candles()
    with bot.storage._conn() as c:
        live = [dict(r) for r in c.execute("SELECT entry_time, exit_time, reason, round(pnl_pct, 6) pnl FROM trades ORDER BY id")]
    bt_trades = [{"entry_time": t.entry_time, "exit_time": t.exit_time, "reason": t.reason, "pnl": round(t.pnl_pct, 6)}
                 for t in bt.trades if pd.Timestamp(t.entry_time) >= pd.Timestamp(rows[29][0], unit="ms", tz="UTC")]
    assert len(bt_trades) > 3
    assert live == bt_trades
