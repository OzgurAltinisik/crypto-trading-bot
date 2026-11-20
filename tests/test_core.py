import numpy as np
import pandas as pd
import pytest

from cryptobot import indicators as ind
from cryptobot.account import PaperAccount
from cryptobot.data import drop_open_candle
from cryptobot.position import Position, check_exit, pnl_pct, update_breakeven
from cryptobot.strategy import EmaCrossParams, EmaCrossStrategy, Levels, build_strategy

FEE = 0.001


def candles(closes, start="2025-01-01", freq="1h", spread=0.5):
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz="UTC")
    c = pd.Series(closes, index=idx, dtype=float)
    o = c.shift(1).fillna(c.iloc[0])
    return pd.DataFrame({
        "open": o, "high": np.maximum(o, c) + spread, "low": np.minimum(o, c) - spread,
        "close": c, "volume": 1.0,
    })


# --- indicators ---
def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up).iloc[-1] == pytest.approx(100)
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(down).iloc[-1] == pytest.approx(0)
    rnd = pd.Series(np.random.default_rng(1).normal(0, 1, 500).cumsum() + 100)
    r = ind.rsi(rnd).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_rsi_wilder_matches_manual_rma():
    s = pd.Series(np.random.default_rng(2).normal(0, 1, 200).cumsum() + 50)
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    expected = 100 - 100 / (1 + g / l)
    pd.testing.assert_series_equal(ind.rsi(s), expected, check_names=False)


def test_atr_constant_range():
    df = candles([100.0] * 50, spread=1.0)
    assert ind.atr(df).iloc[-1] == pytest.approx(2.0)


# --- closed candles ---
def test_drop_open_candle():
    df = candles([1, 2, 3])
    last_open_ms = int(df.index[-1].timestamp() * 1000)
    assert len(drop_open_candle(df, "1h", last_open_ms + 10 * 60_000)) == 2   # forming
    assert len(drop_open_candle(df, "1h", last_open_ms + 3_600_000)) == 3     # closed


# --- strategy ---
def test_signals_have_no_lookahead():
    rng = np.random.default_rng(3)
    closes = rng.normal(0, 1, 600).cumsum() + 1000
    strat = build_strategy("ema_cross", {"fast": 9, "slow": 21, "trend": 200, "rsi_buy_max": 60})
    full = strat.prepare(candles(closes))
    part = strat.prepare(candles(closes[:400]))
    pd.testing.assert_series_equal(full["buy"].iloc[:400], part["buy"])
    pd.testing.assert_series_equal(full["sell"].iloc[:400], part["sell"])
    assert full["buy"].any() and full["sell"].any()


def test_params_validation():
    with pytest.raises(ValueError):
        build_strategy("ema_cross", {"nope": 1})
    with pytest.raises(ValueError):
        build_strategy("ema_cross", {"breakeven_at": 0.5})
    with pytest.raises(ValueError):
        build_strategy("unknown", {})


def test_levels():
    s = EmaCrossStrategy(EmaCrossParams(stop_type="atr", stop_value=2, take_profit_atr=5, breakeven_at=0.5))
    lv = s.levels(100.0, pd.Series({"atr": 1.0}))
    assert (lv.stop, lv.take_profit, lv.breakeven_trigger) == (98.0, 105.0, 102.5)
    s = EmaCrossStrategy(EmaCrossParams(stop_type="pct", stop_value=0.08))
    lv = s.levels(100.0, pd.Series({"atr": 1.0}))
    assert lv.stop == pytest.approx(92.0) and lv.take_profit is None


# --- position ---
def make_pos(stop=98.0, tp=105.0, be=102.5):
    return Position.open("2025-01-01T00:00:00+00:00", 100.0, 0.0, lambda e: Levels(stop, tp, be))


def test_stop_wins_when_both_hit():
    ex = check_exit(make_pos(), open_=100, high=110, low=90)
    assert ex.reason == "STOP-LOSS" and ex.price == 98.0


def test_gap_fills_at_open():
    assert check_exit(make_pos(), open_=95, high=96, low=94).price == 95
    assert check_exit(make_pos(), open_=107, high=108, low=106).price == 107


def test_breakeven_exit_is_flat_after_fees():
    pos = Position.open("t", 100.0, FEE, lambda e: Levels(e - 2, e + 5, e + 2.5))
    assert update_breakeven(pos, pos.entry_price + 3, FEE)
    assert not update_breakeven(pos, pos.entry_price + 3, FEE)   # only once
    assert pnl_pct(pos, pos.stop, FEE) == pytest.approx(0, abs=1e-9)
    assert check_exit(pos, pos.stop, pos.stop, pos.stop).reason == "BREAKEVEN STOP"


# --- account ---
def test_account_round_trip():
    strat = EmaCrossStrategy(EmaCrossParams(stop_type="pct", stop_value=0.1))
    acc = PaperAccount(strat, FEE, 1000.0)
    row = pd.Series({"open": 100, "high": 101, "low": 99, "close": 100, "atr": 1, "buy": True, "sell": False})
    assert acc.on_bar(pd.Timestamp("2025-01-01", tz="UTC"), row)[0].kind == "open"
    row2 = pd.Series({"open": 110, "high": 111, "low": 109, "close": 110, "atr": 1, "buy": True, "sell": True})
    ev = acc.on_bar(pd.Timestamp("2025-01-01 01:00", tz="UTC"), row2)
    assert [e.kind for e in ev] == ["close"] and acc.position is None   # no same-bar re-entry
    expected = 1000 * (110 * (1 - FEE) / (100 * (1 + FEE)))
    assert acc.balance == pytest.approx(expected)


# --- phase 1.5: ADX, Donchian, trailing stop, walk-forward ---
from cryptobot.position import update_trailing


def test_adx_bounds_and_trend():
    trend = candles(np.linspace(100, 200, 300))
    a = ind.adx(trend).iloc[-1]
    assert 0 <= a <= 100 and a > 40          # steady trend -> strong ADX
    rng = np.random.default_rng(4)
    chop = candles(100 + rng.normal(0, 1, 300))
    assert ind.adx(chop).iloc[-1] < a


def test_donchian_signals_no_lookahead():
    rng = np.random.default_rng(5)
    closes = rng.normal(0, 1, 500).cumsum() + 500
    strat = build_strategy("donchian", {"entry_period": 20, "exit_period": 10, "adx_min": 15, "trend": 100})
    full = strat.prepare(candles(closes))
    part = strat.prepare(candles(closes[:300]))
    pd.testing.assert_series_equal(full["buy"].iloc[:300], part["buy"])
    pd.testing.assert_series_equal(full["sell"].iloc[:300], part["sell"])
    assert full["buy"].any()
    # a buy means the close broke the previous 20-bar high
    b = full[full["buy"]]
    assert (b["close"] > b["dc_high"]).all()


def test_trailing_stop_only_moves_up():
    # highest starts at the entry price: 100 - 6 = 94 < initial stop 95
    pos = Position.open("t", 100.0, 0.0, lambda e: Levels(95.0, None, None, trail_distance=6.0))
    assert not update_trailing(pos, 98.0) and pos.stop == 95.0
    assert update_trailing(pos, 112.0) and pos.stop == 106.0
    assert not update_trailing(pos, 105.0) and pos.stop == 106.0
    assert check_exit(pos, 107, 107, 105).reason == "TRAILING STOP"


def test_walk_forward_runs_and_uses_only_past_for_selection():
    from cryptobot.optimize import expand_grid, walk_forward
    rng = np.random.default_rng(6)
    closes = np.exp(rng.normal(0.0002, 0.01, 6000).cumsum()) * 100
    c = candles(closes, start="2020-01-01", freq="4h", spread=0.2)
    combos = expand_grid({"stop_type": "atr"}, {"entry_period": [20, 55], "trail_atr": [None, 3.0]})
    assert len(combos) == 4
    ws = walk_forward(c, "X/USDT", "4h", "donchian", combos, "2020-06-01",
                      train_months=12, test_months=6, min_trades=1)
    assert len(ws) >= 3
    for w in ws:
        assert w.train[1] == w.test[0] and w.test[0] < w.test[1]


# --- position sizing ---
from cryptobot.account import Sizing


def test_sizing_quantity():
    # risk 1% of 10k = $100; loss per unit at stop = 100 - 95 = 5 -> 20 units ($2000 = 20%)
    assert Sizing(0.01).quantity(10_000, 100.0, 95.0, 0.0) == pytest.approx(20)
    # very tight stop would need 200% of balance -> capped at max_position
    assert Sizing(0.01, max_position=1.0).quantity(10_000, 100.0, 99.5, 0.0) == pytest.approx(100)
    assert Sizing(0.01, max_position=0.5).quantity(10_000, 100.0, 99.5, 0.0) == pytest.approx(50)
    assert Sizing(None).quantity(10_000, 100.0, 95.0, 0.0) == pytest.approx(100)
    with pytest.raises(ValueError):
        Sizing(0.01, max_position=2.0)     # no leverage
    with pytest.raises(ValueError):
        Sizing(0.0)


def test_loss_at_stop_equals_risk():
    strat = EmaCrossStrategy(EmaCrossParams(stop_type="pct", stop_value=0.05))
    acc = PaperAccount(strat, FEE, 10_000.0, sizing=Sizing(0.02))
    row = pd.Series({"open": 100, "high": 101, "low": 99, "close": 100, "atr": 1, "buy": True, "sell": False})
    acc.on_bar(pd.Timestamp("2025-01-01", tz="UTC"), row)
    stop = acc.position.stop
    bar = pd.Series({"open": 100, "high": 100, "low": stop - 1, "close": stop, "atr": 1, "buy": False, "sell": False})
    ev = acc.on_bar(pd.Timestamp("2025-01-01 01:00", tz="UTC"), bar)
    t = ev[0].trade
    assert t.reason == "STOP-LOSS"
    assert t.pnl_usd == pytest.approx(-200, rel=1e-9)        # exactly 2% of 10k
    # risk $200 over a ~5.2% stop distance (incl. fees) -> position ~38% of the balance
    assert 35 < t.position_pct < 41


def test_equity_marks_only_the_position():
    strat = EmaCrossStrategy(EmaCrossParams(stop_type="pct", stop_value=0.1))
    acc = PaperAccount(strat, 0.0, 10_000.0, sizing=Sizing(0.01))
    row = pd.Series({"open": 100, "high": 100, "low": 100, "close": 100, "atr": 1, "buy": True, "sell": False})
    acc.on_bar(pd.Timestamp("2025-01-01", tz="UTC"), row)
    q = acc.position.qty
    assert q == pytest.approx(10)                             # $100 risk / $10 stop distance
    assert acc.equity(110) == pytest.approx(10_000 + q * 10)  # +$100, not +10% of the balance


def test_legacy_position_without_qty_is_all_in():
    strat = EmaCrossStrategy(EmaCrossParams(stop_type="pct", stop_value=0.1))
    legacy = Position(entry_time="t", entry_price=100.0, stop=90.0, initial_stop=90.0)
    acc = PaperAccount(strat, 0.0, 1_000.0, position=legacy, sizing=Sizing(0.01))
    t = acc.close(pd.Timestamp("2025-01-02", tz="UTC"), 110.0, "SELL SIGNAL").trade
    assert t.pnl_usd == pytest.approx(100) and t.position_pct == pytest.approx(100)


def test_storage_migrates_old_trades_table(tmp_path):
    import sqlite3
    from cryptobot.storage import Storage
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, bot_id TEXT, symbol TEXT, entry_time TEXT,"
                " entry_price REAL, exit_time TEXT, exit_price REAL, initial_stop REAL, pnl_pct REAL,"
                " pnl_usd REAL, reason TEXT, balance_after REAL)")
    con.commit(); con.close()
    s = Storage(db)
    s.save_trade(bot_id="b", symbol="X", entry_time="a", entry_price=1, exit_time="b", exit_price=1,
                 initial_stop=1, pnl_pct=0, pnl_usd=0, reason="r", balance_after=1, qty=2, position_pct=50)
    assert s.trades("b")[0]["position_pct"] == 50
