"""Telegram command answers, without touching the network."""
import pytest

from cryptobot.config import AppConfig, BotConfig
from cryptobot.notifier import TelegramNotifier
from cryptobot.position import Position
from cryptobot.storage import Storage
from cryptobot.telegram_bot import TelegramCommands, parse_command


@pytest.fixture
def bot_env(tmp_path):
    bots = [
        BotConfig(id="btc", symbol="BTC/USDT", timeframe="4h", strategy_name="donchian", params={}),
        BotConfig(id="eth", symbol="ETH/USDT", timeframe="4h", strategy_name="donchian", params={}),
        BotConfig(id="old", symbol="BTC/USDT", timeframe="1h", strategy_name="donchian", params={}, enabled=False),
    ]
    cfg = AppConfig(exchange="binance", db_path=tmp_path / "bot.db", cache_dir=tmp_path, log_dir=tmp_path,
                    tick_seconds=30, bots=bots)
    storage = Storage(cfg.db_path)
    for b in bots:
        storage.load_state(b.id, 10_000)
    cmds = TelegramCommands("tok", cfg, storage, TelegramNotifier(None, None), {"111", ""},
                            public_url="https://panel.example.com",
                            prices=lambda syms: {"BTC/USDT": 110_000.0, "ETH/USDT": 2_000.0}, public=False)
    return cmds, storage


def msg(text, chat=111):
    return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}


def test_parse_command():
    assert parse_command("/Durum@KriptoBot extra") == "durum"
    assert parse_command("/start") == "yardim"
    assert parse_command("merhaba") is None
    assert parse_command("") is None


def test_unauthorized_chat_gets_its_id(bot_env):
    cmds, _ = bot_env
    chat, reply = cmds.handle_update(msg("/durum", chat=999))
    assert chat == "999" and "999" in reply and "iznin yok" in reply
    assert cmds.handle_update({"update_id": 2, "channel_post": {"chat": {"id": 1}, "text": "/durum"}}) is None
    assert cmds.handle_update(msg("hello")) is None


def test_status_positions_trades(bot_env):
    cmds, storage = bot_env
    _, reply = cmds.handle_update(msg("/durum"))
    assert "Motor henüz çalışmadı" in reply and "BTC/USDT" in reply and "ETH/USDT" in reply
    assert reply.count("Beklemede") == 2            # disabled bot not listed

    assert "Açık pozisyon yok" in cmds.respond("pozisyonlar")
    storage.heartbeat()
    pos = Position(entry_time="2026-11-01T00:00:00+00:00", entry_price=100_000.0, stop=95_000.0, initial_stop=95_000.0, qty=0.05)
    storage.save_state("btc", 10_000, pos, None)
    out = cmds.respond("pozisyonlar")
    assert "BTC/USDT" in out and "+9.89%" in out    # 110k * 0.999 / 100k - 1
    assert "Motor çalışıyor" in cmds.respond("durum")

    assert "Henüz kapanmış işlem yok" in cmds.respond("islemler")
    storage.save_trade(bot_id="btc", symbol="BTC/USDT", entry_time="a", entry_price=1, exit_time="2026-11-05T00:00:00",
                       exit_price=1, initial_stop=1, pnl_pct=4.2, pnl_usd=120, reason="SELL SIGNAL", balance_after=1)
    assert "+4.20%" in cmds.respond("islemler")
    assert "panel.example.com" in cmds.respond("panel")
    assert "/durum" in cmds.respond("yardim")
    assert "tanımıyorum" in cmds.respond("xyz")
