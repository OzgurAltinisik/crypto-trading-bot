"""Dashboard API against a fake exchange and a temporary database."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cryptobot.api import create_app
from cryptobot.config import AppConfig, BotConfig
from cryptobot.position import Position
from cryptobot.storage import Storage

HOUR = 3_600_000


class FakeExchange:
    id = "fake"

    def __init__(self, n=1200):
        rng = np.random.default_rng(1)
        closes = np.exp(rng.normal(0.0003, 0.01, n).cumsum()) * 100
        start = 1_700_000_000_000 - (1_700_000_000_000 % (4 * HOUR))
        self.rows, prev = [], closes[0]
        for i, c in enumerate(closes):
            self.rows.append([start + i * 4 * HOUR, prev, max(prev, c) * 1.002, min(prev, c) * 0.998, c, 1.0])
            prev = c
        self.now = self.rows[-1][0] + 4 * HOUR + 1000

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, symbol, timeframe, limit=1000, since=None):
        rows = self.rows if since is None else [r for r in self.rows if r[0] >= since]
        return rows[-limit:] if since is None else rows[:limit]

    def fetch_tickers(self, symbols):
        return {s: {"last": self.rows[-1][4], "percentage": 1.5} for s in symbols}


@pytest.fixture
def setup(tmp_path):
    bot = BotConfig(id="x_donchian", symbol="X/USDT", timeframe="4h", strategy_name="donchian",
                    params={"entry_period": 20, "exit_period": 10, "stop_type": "atr", "stop_value": 2.0})
    disabled = BotConfig(id="off", symbol="X/USDT", timeframe="4h", strategy_name="donchian", params={}, enabled=False)
    cfg = AppConfig(exchange="binance", db_path=tmp_path / "bot.db", cache_dir=tmp_path / "cache",
                    log_dir=tmp_path / "logs", tick_seconds=30, bots=[bot, disabled])
    storage = Storage(cfg.db_path)
    storage.load_state(bot.id, 10_000)
    return cfg, storage, FakeExchange()


def test_overview_and_engine_status(setup):
    cfg, storage, ex = setup
    c = TestClient(create_app(cfg, ex, dashboard_key=""))
    d = c.get("/api/overview").json()
    assert d["engine"]["online"] is False
    assert [b["id"] for b in d["bots"]] == ["x_donchian"]          # disabled bot hidden
    assert d["bots"][0]["price"] == pytest.approx(ex.rows[-1][4])

    storage.heartbeat()
    pos = Position(entry_time="2025-01-01T00:00:00+00:00", entry_price=ex.rows[-1][4] / 1.1,
                   stop=1.0, initial_stop=1.0)
    storage.save_state("x_donchian", 10_000, pos, None)
    d = c.get("/api/overview").json()
    assert d["engine"]["online"] is True
    assert d["bots"][0]["position"]["unrealized_pct"] == pytest.approx((1.1 * 0.999 - 1) * 100)


def test_chart_backtest_trades_signals(setup):
    cfg, storage, ex = setup
    c = TestClient(create_app(cfg, ex, dashboard_key=""))
    ch = c.get("/api/bots/x_donchian/chart?days=30").json()
    assert len(ch["candles"]) == 30 * 6 + 1          # 4h candles, both ends included
    assert len(c.get("/api/bots/x_donchian/chart?days=9999").json()["candles"]) > 180
    assert {"Kanal üst", "Kanal alt"} <= set(ch["lines"])
    times = [m["time"] for m in ch["markers"]]
    assert times == sorted(times)

    bt = c.get("/api/bots/x_donchian/backtest")
    assert bt.status_code == 200
    m = bt.json()["metrics"]
    assert m["trades"] > 0 and "buy_hold_return_pct" in m

    storage.save_trade(bot_id="x_donchian", symbol="X/USDT", entry_time="2025-01-01T00:00:00+00:00",
                       entry_price=100, exit_time="2025-01-02T00:00:00+00:00", exit_price=110,
                       initial_stop=95, pnl_pct=9.8, pnl_usd=980, reason="SELL SIGNAL", balance_after=10980)
    storage.save_signal("x_donchian", "X/USDT", "2025-01-01T00:00:00+00:00", "BUY", 100, True)
    assert len(c.get("/api/trades").json()) == 1
    assert c.get("/api/signals?bot_id=x_donchian").json()[0]["side"] == "BUY"
    assert c.get("/api/bots/nope/chart").status_code == 404
    assert c.get("/api/trades?bot_id=off").status_code == 404


def test_invite_key(setup):
    cfg, _, ex = setup
    c = TestClient(create_app(cfg, ex, dashboard_key="s3cret"))
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/overview").status_code == 401
    assert c.get("/").status_code == 401
    assert c.get("/?key=wrong").status_code == 401
    r = c.get("/?key=s3cret", follow_redirects=False)
    assert r.status_code == 303 and "key=" not in r.headers["location"]
    # cookie is now set on the client
    assert c.get("/api/overview").status_code == 200
    assert c.get("/").status_code in (200, 503)   # 503 = frontend not built yet
