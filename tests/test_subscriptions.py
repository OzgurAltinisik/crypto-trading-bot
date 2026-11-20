"""Subscriptions: sign-up flow, alert fan-out, the outbox sender, Telegram /abone."""
import re

import pytest
from fastapi.testclient import TestClient

from cryptobot import alerts
from cryptobot.api import create_app
from cryptobot.config import AppConfig, BotConfig
from cryptobot.notifier import TelegramNotifier
from cryptobot.storage import Storage
from cryptobot.telegram_bot import TelegramCommands
from tests.test_api import FakeExchange


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://panel.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    bots = [
        BotConfig(id="btc_d", symbol="BTC/USDT", timeframe="4h", strategy_name="donchian", params={}),
        BotConfig(id="eth_d", symbol="ETH/USDT", timeframe="4h", strategy_name="donchian", params={}),
        BotConfig(id="btc_ema", symbol="BTC/USDT", timeframe="4h", strategy_name="ema_cross", params={"fast": 50, "slow": 200}),
    ]
    cfg = AppConfig(exchange="binance", db_path=tmp_path / "bot.db", cache_dir=tmp_path / "c", log_dir=tmp_path,
                    tick_seconds=30, bots=bots)
    storage = Storage(cfg.db_path)
    client = TestClient(create_app(cfg, FakeExchange(), dashboard_key=""))
    return cfg, storage, client


def outbox(storage):
    with storage._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM outbox ORDER BY id")]


def token_from(text):
    return re.search(r"token=([\w\-]+)", text).group(1)


# ------------------------------------------------------------------ web flow
def test_signup_confirm_manage_unsubscribe(env):
    _, storage, c = env
    r = c.post("/api/subscriptions", json={"email": " Ali@Example.com ", "bots": ["btc_d"], "events": "entry"})
    assert r.status_code == 202
    sub = storage.get_subscriber("email", "ali@example.com")
    assert sub and not sub["confirmed"] and sub["bots"] == ["btc_d"]
    mails = outbox(storage)
    assert len(mails) == 1 and "onayla" in mails[0]["subject"]
    token = token_from(mails[0]["body_text"])
    assert token == sub["token"]

    # not confirmed -> gets no alerts
    assert storage.subscribers_for("btc_d", "entry") == []

    r = c.get(f"/api/subscriptions/confirm?token={token}", follow_redirects=False)
    assert r.status_code == 303 and "durum=onaylandi" in r.headers["location"]
    assert storage.subscriber_by_token(token)["confirmed"]

    got = c.get(f"/api/subscriptions/{token}").json()
    assert got["address"] == "al***@example.com" and got["confirmed"] and got["events"] == "entry"

    r = c.put(f"/api/subscriptions/{token}", json={"bots": ["btc_d", "eth_d"], "events": "all"})
    assert r.json()["bots"] == ["btc_d", "eth_d"]
    assert len(storage.subscribers_for("eth_d", "exit")) == 1

    # GET on the unsubscribe link only shows a page (mail scanners!)
    r = c.get(f"/api/subscriptions/unsubscribe?token={token}", follow_redirects=False)
    assert r.status_code == 303 and "cik=1" in r.headers["location"]
    assert storage.subscriber_by_token(token)
    # RFC 8058 one-click POST deletes
    assert c.post(f"/api/subscriptions/unsubscribe?token={token}").status_code == 200
    assert storage.subscriber_by_token(token) is None
    assert c.get(f"/api/subscriptions/{token}").status_code == 404


def test_confirmed_address_cannot_be_changed_without_link(env):
    _, storage, c = env
    c.post("/api/subscriptions", json={"email": "a@b.co", "bots": ["btc_d"], "events": "all"})
    token = storage.get_subscriber("email", "a@b.co")["token"]
    storage.update_subscriber(token, confirmed=True, confirm_sent_at="2000-01-01T00:00:00+00:00")
    r = c.post("/api/subscriptions", json={"email": "a@b.co", "bots": ["eth_d"], "events": "entry"})
    assert r.status_code == 202                                   # same answer as for a new address
    sub = storage.subscriber_by_token(token)
    assert sub["bots"] == ["btc_d"] and sub["events"] == "all"   # unchanged
    assert "tercihlerin" in outbox(storage)[-1]["subject"]        # owner gets the manage link instead


def test_validation_honeypot_and_rate_limit(env):
    _, storage, c = env
    assert c.post("/api/subscriptions", json={"email": "not-an-email", "bots": ["btc_d"]}).status_code == 422
    assert c.post("/api/subscriptions", json={"email": "x@y.co", "bots": ["nope"]}).status_code == 422
    assert c.post("/api/subscriptions", json={"email": "x@y.co", "bots": ["btc_d"], "events": "weird"}).status_code == 422
    # honeypot filled: looks like success, stores nothing
    assert c.post("/api/subscriptions", json={"email": "bot@spam.co", "bots": ["btc_d"], "website": "x"}).status_code == 202
    assert storage.get_subscriber("email", "bot@spam.co") is None
    codes = [c.post("/api/subscriptions", json={"email": f"u{i}@y.co", "bots": ["btc_d"]}).status_code for i in range(8)]
    assert 429 in codes and codes[0] == 202


def test_config_and_last_activity(env):
    _, storage, c = env
    cfg = c.get("/api/config").json()
    assert cfg["email_enabled"] and [b["id"] for b in cfg["bots"]] == ["btc_d", "eth_d", "btc_ema"]
    storage.save_trade(bot_id="btc_d", symbol="BTC/USDT", entry_time="a", entry_price=1, exit_time="2026-11-01T00:00:00+00:00",
                       exit_price=1, initial_stop=1, pnl_pct=1, pnl_usd=1, reason="SELL SIGNAL", balance_after=1)
    bots = {b["id"]: b for b in c.get("/api/overview").json()["bots"]}
    assert bots["btc_d"]["last_exit"] == "2026-11-01T00:00:00+00:00" and bots["eth_d"]["last_exit"] is None


def test_manage_page_served_without_invite_key(env, tmp_path):
    cfg, storage, _ = env
    c = TestClient(create_app(cfg, FakeExchange(), dashboard_key="secret"))
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/subscriptions/nope").status_code == 404     # reachable, just unknown
    assert c.post("/api/subscriptions", json={"email": "a@b.co", "bots": ["btc_d"]}).status_code == 401
    assert c.get("/abonelik").status_code in (200, 503)


# ------------------------------------------------------------------ alerts
def test_trade_alerts_fan_out_and_dedupe(env):
    _, storage, _ = env
    a = storage.upsert_subscriber("email", "a@x.co", "tokA", ["btc_d"], "all", confirmed=True)
    storage.upsert_subscriber("email", "b@x.co", "tokB", ["btc_d"], "entry", confirmed=True)
    storage.upsert_subscriber("email", "c@x.co", "tokC", ["btc_d"], "all")             # unconfirmed
    storage.upsert_subscriber("telegram", "555", "tokT", ["eth_d", "btc_d"], "all", confirmed=True)

    n = alerts.queue_trade_alerts(storage, "entry", "btc_d", "BTC/USDT", "4h", "2026-11-11T08:00:00+00:00",
                                  entry_price=100_000.0, stop=97_000.0)
    assert n == 3
    again = alerts.queue_trade_alerts(storage, "entry", "btc_d", "BTC/USDT", "4h", "2026-11-11T08:00:00+00:00",
                                      entry_price=100_000.0, stop=97_000.0)
    assert again == 0                                             # restart replay: nothing new
    n = alerts.queue_trade_alerts(storage, "exit", "btc_d", "BTC/USDT", "4h", "2026-11-12T08:00:00+00:00",
                                  entry_price=100_000.0, exit_price=104_000.0, pnl_pct=3.8, reason="SELL SIGNAL")
    assert n == 2                                                 # 'entry'-only subscriber skipped
    mails = [m for m in outbox(storage) if m["channel"] == "email"]
    assert all(m["unsubscribe_url"].endswith("token=" + ("tokA" if m["address"] == "a@x.co" else "tokB")) for m in mails)
    assert "BTC/USDT botu işleme girdi" in mails[0]["subject"] and "$100,000.00" in mails[0]["subject"]
    assert "https://panel.test/?bot=btc_d" in mails[0]["body_text"]
    assert a["token"] == "tokA"


class FakeMail:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def build(self, *args):
        return alerts.EmailSender("h", 587, "u", "p", "bot@gmail.com").build(*args)

    def send(self, msg):
        if self.fail:
            raise OSError("smtp down")
        self.sent.append(msg)


class FakeResp:
    def __init__(self, ok=True, desc=""):
        self.status_code = 200 if ok else 403
        self._b = {"ok": ok, "description": desc}

    def json(self):
        return self._b


def test_outbox_sender_sends_retries_and_headers(env):
    _, storage, _ = env
    storage.upsert_subscriber("telegram", "777", "tokT", ["btc_d"], "all", confirmed=True)
    storage.enqueue("email", "a@x.co", "hello", "Subj", "<p>hi</p>", "https://panel.test/api/subscriptions/unsubscribe?token=t")
    storage.enqueue("telegram", "777", "<b>hi</b>")

    calls = []
    mail = FakeMail()
    sender = alerts.OutboxSender(storage, mail, "tok", telegram_post=lambda url, **kw: calls.append(kw) or FakeResp())
    assert sender.run_once() == 2
    assert sender.run_once() == 0                                 # nothing left
    m = mail.sent[0]
    assert m["To"] == "a@x.co" and m["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "unsubscribe?token=t" in m["List-Unsubscribe"]
    assert calls[0]["data"]["chat_id"] == "777"

    # failure: retried later, not lost
    storage.enqueue("email", "b@x.co", "x", "S")
    failing = alerts.OutboxSender(storage, FakeMail(fail=True), "tok")
    assert failing.run_once() == 0
    row = outbox(storage)[-1]
    assert row["attempts"] == 1 and "smtp down" in row["last_error"] and row["sent_at"] is None

    # user blocked the bot: subscriber removed
    storage.enqueue("telegram", "777", "x2")
    blocked = alerts.OutboxSender(storage, None, "tok", telegram_post=lambda url, **kw: FakeResp(False, "Forbidden: bot was blocked by the user"))
    blocked.run_once()
    assert storage.get_subscriber("telegram", "777") is None


def test_emails_wait_when_smtp_not_configured(env):
    _, storage, _ = env
    storage.enqueue("email", "a@x.co", "hello", "Subj")
    assert alerts.OutboxSender(storage, None, None).run_once() == 0
    assert outbox(storage)[0]["attempts"] == 0                    # kept for later


# ------------------------------------------------------------------ telegram
def test_telegram_subscribe_commands(env):
    cfg, storage, _ = env
    t = TelegramCommands("tok", cfg, storage, TelegramNotifier(None, None), set(), prices=lambda s: {})

    def say(text, chat=42):
        return t.handle_update({"update_id": 1, "message": {"chat": {"id": chat}, "text": text}})[1]

    assert "Hangi bot" in say("/abone")
    assert "Hangi bot" in say("/abone doge")
    assert "BTC (4h)" in say("/abone btc")
    sub = storage.get_subscriber("telegram", "42")
    assert sub["bots"] == ["btc_d"] and sub["events"] == "all" and sub["confirmed"]   # coin -> first bot
    assert "sadece alımlar" in say("/abone eth alim")
    sub = storage.get_subscriber("telegram", "42")
    assert sub["bots"] == ["btc_d", "eth_d"] and sub["events"] == "entry"
    assert "ETH" in say("/aboneliklerim")
    assert "Kalan" in say("/iptal btc")
    assert storage.get_subscriber("telegram", "42")["bots"] == ["eth_d"]
    assert "durduruldu" in say("/iptal")
    assert storage.get_subscriber("telegram", "42") is None
    assert "Zaten" in say("/iptal")
    say("/abone hepsi")
    assert storage.get_subscriber("telegram", "42")["bots"] == ["btc_d", "eth_d", "btc_ema"]
    assert "btc_ema" in say("/botlar")


def test_engine_queues_alert_when_position_opens(tmp_path):
    from tests.test_engine import FakeExchange as EngineExchange, bot_cfg, crossing_series, rows_from
    from cryptobot.engine import LiveBot

    storage = Storage(tmp_path / "bot.db")
    storage.upsert_subscriber("email", "a@x.co", "tokA", ["t"], "entry", confirmed=True)
    bot = LiveBot(bot_cfg(), EngineExchange(rows_from(crossing_series())), storage, TelegramNotifier(None, None))
    bot.tick()
    assert bot.account.position is not None
    rows = outbox(storage)
    assert len(rows) == 1 and rows[0]["address"] == "a@x.co" and "işleme girdi" in rows[0]["subject"]


def test_telegram_status_filter(env):
    cfg, storage, _ = env
    t = TelegramCommands("tok", cfg, storage, TelegramNotifier(None, None), set(),
                         prices=lambda s: {"BTC/USDT": 90_000.0, "ETH/USDT": 2_000.0})
    for b in cfg.bots:
        storage.load_state(b.id, 10_000)
    one = t.respond("durum", ["btc"])
    assert one.count("BTC/USDT") == 2 and "ETH/USDT" not in one      # both BTC bots, nothing else
    assert "Son işlem: henüz yok" in one and "/abone btc" in one
    every = t.respond("durum", ["hepsi"])
    assert "ETH/USDT" in every and every == t.respond("durum", [])
    assert "Bu coin için bot yok" in t.respond("durum", ["doge"])
    assert "Açık pozisyon yok" in t.respond("pozisyonlar", ["eth"])


def test_test_alert_command(env, capsys):
    from cryptobot.__main__ import cmd_test_alert
    cfg, storage, _ = env
    cmd_test_alert(cfg, None)
    assert "No subscribers" in capsys.readouterr().out
    storage.upsert_subscriber("telegram", "42", "tokT", ["btc_d", "eth_d"], "all", confirmed=True)
    storage.upsert_subscriber("telegram", "43", "tokU", ["btc_d"], "all")          # unconfirmed: skipped
    cmd_test_alert(cfg, None)
    rows = outbox(storage)
    assert len(rows) == 1 and rows[0]["address"] == "42" and "BTC, ETH" in rows[0]["body_text"]
