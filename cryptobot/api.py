"""Read-only web API + dashboard.

    python -m cryptobot serve            # http://localhost:8000

The engine writes to SQLite; this process only reads it, plus public market
data from Binance for prices and charts. Everyone who opens the dashboard
sees the same data. If DASHBOARD_KEY is set, the dashboard is only reachable
through an invite link: https://your-host/?key=<DASHBOARD_KEY>
"""
from __future__ import annotations

import hmac
import logging
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import alerts
from .backtest import run_backtest
from .config import AppConfig, BotConfig
from .data import fetch_history, make_exchange, timeframe_ms, with_retry
from .storage import Storage

log = logging.getLogger(__name__)

DIST_DIR = Path(__file__).resolve().parent / "web" / "dist"   # built by `npm run build` in frontend/
COOKIE = "cb_key"
ENGINE_STALE_SECONDS = 180
BACKTEST_START = "2024-01-01"
MAX_CHART_DAYS = 3 * 365


# ---------- helpers ----------
def clean(v):
    """JSON-safe: NaN/inf -> None, numpy scalars -> python."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def unix(ts) -> int:
    return int(pd.Timestamp(ts).timestamp())


def floor_to_candle(ts, tf_ms: int) -> int:
    ms = int(pd.Timestamp(ts).timestamp() * 1000)
    return (ms // tf_ms) * tf_ms // 1000


class TTLCache:
    def __init__(self):
        self._d: dict = {}
        self._lock = threading.Lock()

    def get(self, key, ttl: float, fn: Callable):
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        val = fn()
        with self._lock:
            self._d[key] = (time.monotonic(), val)
        return val


# ---------- market data service ----------
class Market:
    def __init__(self, config: AppConfig, exchange=None):
        self.config = config
        self.exchange = exchange or make_exchange(config.exchange)
        self.cache = TTLCache()

    def prices(self, symbols: list[str]) -> dict:
        def load():
            try:
                t = with_retry(self.exchange.fetch_tickers, symbols)
                return {s: {"last": t[s]["last"], "change_24h_pct": t[s].get("percentage")} for s in symbols if s in t}
            except Exception:
                log.exception("Ticker fetch failed")
                return {}
        return self.cache.get(("prices", tuple(sorted(symbols))), 10, load)

    def prepared(self, bot: BotConfig) -> pd.DataFrame:
        """Closed candles for the last MAX_CHART_DAYS (+ indicator warm-up) with the
        bot's indicators. Uses the CSV candle cache, so a refresh only downloads the
        newest candles; refreshed each minute."""
        def load():
            warm = pd.Timedelta(milliseconds=timeframe_ms(bot.timeframe) * bot.strategy.warmup_bars)
            since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=MAX_CHART_DAYS) - warm
            candles = fetch_history(self.exchange, bot.symbol, bot.timeframe, since, cache_dir=self.config.cache_dir)
            return bot.strategy.prepare(candles)
        return self.cache.get(("candles", bot.id), 60, load)

    def backtest(self, bot: BotConfig):
        def load():
            start = pd.Timestamp(BACKTEST_START, tz="UTC")
            warm = start - pd.Timedelta(milliseconds=timeframe_ms(bot.timeframe) * bot.strategy.warmup_bars)
            candles = fetch_history(self.exchange, bot.symbol, bot.timeframe, warm, cache_dir=self.config.cache_dir)
            return run_backtest(bot, BACKTEST_START, candles=candles)
        return self.cache.get(("backtest", bot.id), 6 * 3600, load)


# ---------- app ----------
def create_app(config: AppConfig, exchange=None, dashboard_key: Optional[str] = None) -> FastAPI:
    storage = Storage(config.db_path)
    market = Market(config, exchange)
    bots = {b.id: b for b in config.bots if b.enabled}
    key = dashboard_key if dashboard_key is not None else os.getenv("DASHBOARD_KEY") or None

    app = FastAPI(title="Crypto Signal Dashboard", docs_url="/api/docs", openapi_url="/api/openapi.json")

    # --- invite-link access ---
    @app.middleware("http")
    async def access(request: Request, call_next):
        path = request.url.path
        # confirmation / manage / unsubscribe links and the static UI work without the invite key
        token_link = path.startswith("/api/subscriptions") and not (path == "/api/subscriptions" and request.method == "POST")
        if not key or path == "/api/health" or token_link or path.startswith(("/assets/", "/abonelik", "/gizlilik")) \
                or path == "/favicon.svg":
            return await call_next(request)
        given = request.query_params.get("key")
        if given and hmac.compare_digest(given, key):
            # remember the key in a cookie and strip it from the URL
            resp = RedirectResponse(request.url.remove_query_params("key"), status_code=303)
            resp.set_cookie(COOKIE, key, max_age=180 * 86400, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
            return resp
        cookie = request.cookies.get(COOKIE, "")
        if cookie and hmac.compare_digest(cookie, key):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "invite link required"}, status_code=401)
        return HTMLResponse(LOCKED_PAGE, status_code=401)

    def get_bot(bot_id: str) -> BotConfig:
        if bot_id not in bots:
            raise HTTPException(404, f"unknown bot '{bot_id}'")
        return bots[bot_id]

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/overview")
    def overview():
        states = storage.all_states()
        prices = market.prices(sorted({b.symbol for b in bots.values()}))
        hb = storage.last_heartbeat()
        online = False
        if hb:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()
            online = age < ENGINE_STALE_SECONDS
        activity = storage.last_activity()
        out = []
        for b in bots.values():
            st = states.get(b.id, {})
            act = activity.get(b.id, {})
            s = storage.trade_summary(b.id)
            price = prices.get(b.symbol, {})
            pos = st.get("position")
            if pos and price.get("last"):
                pos = dict(pos)
                pos["unrealized_pct"] = (price["last"] * (1 - b.fee) / pos["entry_price"] - 1) * 100
            out.append({
                "id": b.id, "symbol": b.symbol, "timeframe": b.timeframe,
                "strategy": b.strategy_name, "description": b.strategy.describe(),
                "risk_per_trade_pct": b.sizing.risk_per_trade * 100 if b.sizing.risk_per_trade else None,
                "initial_balance": b.initial_balance,
                "balance": st.get("balance", b.initial_balance),
                "position": pos,
                "last_candle": st.get("last_candle"),
                "last_exit": act.get("last_exit"),
                "last_signal": act.get("last_signal"),
                "price": price.get("last"), "change_24h_pct": price.get("change_24h_pct"),
                "stats": {
                    "trades": s["n"], "wins": s["wins"], "net_usd": s["net"],
                    "win_rate_pct": (s["wins"] / s["n"] * 100) if s["n"] else None,
                },
            })
        return clean({"engine": {"heartbeat": hb, "online": online}, "bots": out,
                      "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    @app.get("/api/bots/{bot_id}/chart")
    def chart(bot_id: str, days: int = 365):
        b = get_bot(bot_id)
        days = max(7, min(days, MAX_CHART_DAYS))
        try:
            df = market.prepared(b)
            df = df[df.index >= df.index[-1] - pd.Timedelta(days=days)]
        except Exception as e:
            log.exception("Chart data failed")
            raise HTTPException(502, f"market data unavailable: {e}")
        tf_ms = timeframe_ms(b.timeframe)
        times = [unix(t) for t in df.index]
        candles = [
            {"time": t, "open": o, "high": h, "low": l, "close": c}
            for t, o, h, l, c in zip(times, df["open"], df["high"], df["low"], df["close"])
        ]
        line_cols = {"ema_fast": "EMA hızlı", "ema_slow": "EMA yavaş", "ema_trend": "EMA trend",
                     "dc_high": "Kanal üst", "dc_low": "Kanal alt"}
        lines = {
            label: [{"time": t, "value": v} for t, v in zip(times, df[col]) if not pd.isna(v)]
            for col, label in line_cols.items() if col in df
        }
        first = times[0] if times else 0
        markers = []

        def add_trade_markers(trades, source):
            for t in trades:
                et = floor_to_candle(t["entry_time"], tf_ms)
                xt = floor_to_candle(t["exit_time"], tf_ms)
                if et >= first:
                    markers.append({"time": et, "kind": "entry", "source": source, "price": t["entry_price"]})
                if xt >= first:
                    markers.append({"time": xt, "kind": "exit", "source": source, "price": t["exit_price"],
                                    "pnl_pct": t["pnl_pct"], "reason": t["reason"]})

        add_trade_markers(storage.trades(b.id, 500), "paper")
        try:
            bt = market.backtest(b)
            add_trade_markers([t.__dict__ for t in bt.trades], "backtest")
        except Exception:
            log.exception("Backtest for chart failed")
        markers.sort(key=lambda m: m["time"])
        pos = storage.all_states().get(b.id, {}).get("position")
        return clean({"candles": candles, "lines": lines, "markers": markers, "position": pos})

    @app.get("/api/bots/{bot_id}/backtest")
    def backtest(bot_id: str):
        b = get_bot(bot_id)
        try:
            r = market.backtest(b)
        except Exception as e:
            log.exception("Backtest failed")
            raise HTTPException(502, f"backtest unavailable: {e}")
        m = r.metrics()
        step = max(1, len(r.equity) // 600)
        eq = r.equity.iloc[::step]
        bh = r.initial_balance * r.prices["close"] / r.prices["close"].iloc[0]
        bh = bh.iloc[::step]
        trades = [t.__dict__ for t in r.trades][-50:][::-1]
        return clean({
            "start": BACKTEST_START, "metrics": m,
            "equity": [{"time": unix(t), "value": v} for t, v in eq.items()],
            "buy_hold": [{"time": unix(t), "value": v} for t, v in bh.items()],
            "trades": trades,
        })

    @app.get("/api/trades")
    def trades(bot_id: Optional[str] = None, limit: int = 100):
        if bot_id:
            get_bot(bot_id)
        return clean(storage.trades(bot_id, max(1, min(limit, 1000))))

    @app.get("/api/signals")
    def signals(bot_id: Optional[str] = None, limit: int = 50):
        if bot_id:
            get_bot(bot_id)
        return clean(storage.signals(bot_id, max(1, min(limit, 500))))

    # ---------------- subscriptions ----------------
    limiter = RateLimiter(max_hits=5, window_seconds=15 * 60)
    bot_names = {b.id: f"{b.symbol.split('/')[0]} ({b.timeframe})" for b in bots.values()}

    def check_prefs(bot_ids: list[str], events: str) -> list[str]:
        ids = list(dict.fromkeys(bot_ids))
        if not ids or any(i not in bots for i in ids):
            raise HTTPException(422, "Geçersiz bot seçimi")
        if events not in alerts.EVENTS:
            raise HTTPException(422, "Geçersiz bildirim türü")
        return ids

    def public_sub(sub: dict) -> dict:
        return {"channel": sub["channel"], "address": mask(sub["address"], sub["channel"]), "bots": sub["bots"],
                "events": sub["events"], "confirmed": sub["confirmed"]}

    @app.get("/api/config")
    def site_config():
        return {
            "email_enabled": bool(os.getenv("SMTP_HOST")),
            "telegram_bot": os.getenv("TELEGRAM_BOT_USERNAME") or None,
            "contact_email": os.getenv("CONTACT_EMAIL") or None,
            "bots": [{"id": b.id, "name": bot_names[b.id], "symbol": b.symbol, "strategy": b.strategy_name}
                     for b in bots.values()],
        }

    @app.post("/api/subscriptions", status_code=202)
    def subscribe(body: SubscribeIn, request: Request):
        # same answer whether or not the address is new: no way to probe who is subscribed
        done = {"ok": True, "message": "Onay maili gönderildi. Gelen kutunu ve spam klasörünü kontrol et."}
        if body.website:                       # honeypot field, invisible to people
            return done
        ip = request.client.host if request.client else "?"
        if not limiter.hit(ip):
            raise HTTPException(429, "Çok fazla deneme. Biraz sonra tekrar dene.")
        email = body.email.strip().lower()
        if len(email) > 254 or not EMAIL_RE.match(email):
            raise HTTPException(422, "Geçerli bir e-posta adresi yaz.")
        ids = check_prefs(body.bots, body.events)
        existing = storage.get_subscriber("email", email)
        if existing and existing["confirmed"]:
            # changing a confirmed subscription needs its secret link: mail it to the owner
            if recently(existing.get("confirm_sent_at"), 600):
                return done
            r = alerts.render_manage_link(existing["token"])
            storage.enqueue("email", email, r.text, r.subject, r.html, alerts.unsubscribe_url(existing["token"]))
            storage.update_subscriber(existing["token"], confirm_sent_at=now_iso())
            return done
        sub = storage.upsert_subscriber("email", email, alerts.new_token(), ids, body.events)
        if recently(sub.get("confirm_sent_at"), 600):
            return done
        r = alerts.render_confirmation(sub["token"], ids, body.events, bot_names)
        storage.enqueue("email", email, r.text, r.subject, r.html)
        storage.update_subscriber(sub["token"], confirm_sent_at=now_iso())
        return done

    @app.get("/api/subscriptions/confirm", include_in_schema=False)
    def confirm(token: str = ""):
        sub = storage.subscriber_by_token(token) if token else None
        if not sub:
            return RedirectResponse("/abonelik?durum=gecersiz", status_code=303)
        storage.update_subscriber(token, confirmed=True)
        return RedirectResponse(f"/abonelik?token={token}&durum=onaylandi", status_code=303)

    @app.get("/api/subscriptions/unsubscribe", include_in_schema=False)
    def unsubscribe_page(token: str = ""):
        # mail scanners open links: GET only shows the page, the button there does the POST
        return RedirectResponse(f"/abonelik?token={token}&cik=1", status_code=303)

    @app.post("/api/subscriptions/unsubscribe")
    def unsubscribe_one_click(token: str = ""):
        """RFC 8058 one-click unsubscribe (the mail client's 'Unsubscribe' button)."""
        storage.delete_subscriber(token)
        return {"ok": True}

    @app.get("/api/subscriptions/{token}")
    def get_subscription(token: str):
        sub = storage.subscriber_by_token(token)
        if not sub:
            raise HTTPException(404, "Abonelik bulunamadı")
        return public_sub(sub)

    @app.put("/api/subscriptions/{token}")
    def update_subscription(token: str, body: PrefsIn):
        if not storage.subscriber_by_token(token):
            raise HTTPException(404, "Abonelik bulunamadı")
        ids = check_prefs(body.bots, body.events)
        return public_sub(storage.update_subscriber(token, bots=ids, events=body.events))

    @app.delete("/api/subscriptions/{token}")
    def delete_subscription(token: str):
        if not storage.delete_subscriber(token):
            raise HTTPException(404, "Abonelik bulunamadı")
        return {"ok": True}

    # ---------------- pages (client-side routes share index.html) ----------------
    @app.get("/abonelik", include_in_schema=False)
    @app.get("/gizlilik", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    def index():
        page = DIST_DIR / "index.html"
        if not page.exists():
            return HTMLResponse(NOT_BUILT_PAGE, status_code=503)
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        icon = DIST_DIR / "favicon.svg"
        if not icon.exists():
            raise HTTPException(404)
        return FileResponse(icon)

    # hashed file names -> safe to cache; check_dir=False so the API works before the first build
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets", check_dir=False), name="assets")
    return app


EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9.\-]+\.[a-z]{2,}$")


class SubscribeIn(BaseModel):
    email: str = Field(max_length=254)
    bots: list[str] = Field(min_length=1, max_length=20)
    events: str = "all"
    website: str = ""                     # honeypot


class PrefsIn(BaseModel):
    bots: list[str] = Field(min_length=1, max_length=20)
    events: str = "all"


class RateLimiter:
    """Sliding window per key (client IP), in memory."""

    def __init__(self, max_hits: int, window_seconds: float):
        self.max_hits, self.window = max_hits, window_seconds
        self.hits: dict = defaultdict(deque)
        self.lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_hits:
                return False
            q.append(now)
            return True


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def recently(iso: Optional[str], seconds: float) -> bool:
    if not iso:
        return False
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() < seconds


def mask(address: str, channel: str) -> str:
    """oz***@gmail.com: shown on the manage page, which is reachable by secret link only."""
    if channel != "email" or "@" not in address:
        return "Telegram"
    name, domain = address.split("@", 1)
    return name[:2] + "***@" + domain


_PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Kripto Sinyal Paneli</title>
<style>:root{--bg:#efefef;--paper:#fbfbfb;--ink:#151515;--muted:#7b7b7b;--line:#e2e2e2;--hatch:rgba(0,0,0,.06)}
@media(prefers-color-scheme:dark){:root{--bg:#0b0b0b;--paper:#121212;--ink:#eee;--muted:#8d8d8d;--line:#262626;--hatch:rgba(255,255,255,.05)}}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;box-sizing:border-box;color:var(--ink);
font:15px/1.5 Manrope,system-ui,sans-serif;background:var(--bg) repeating-linear-gradient(135deg,var(--hatch) 0 1px,transparent 1px 10px)}
div{max-width:380px;text-align:center;background:var(--paper);border:1px solid var(--line);padding:32px}
h1{font-size:20px;margin:0 0 8px;letter-spacing:-.02em}p{color:var(--muted);margin:0}code{font-size:13px}</style></head>
<body><div><h1>%s</h1><p>%s</p></div></body></html>"""
LOCKED_PAGE = _PAGE % ("Davet linki gerekli", "Bu panel sadece davet linkiyle açılır. Linki paylaşan kişiden yeni bir link iste.")
NOT_BUILT_PAGE = _PAGE % ("Arayüz henüz derlenmedi",
                          "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code> komutunu çalıştır. "
                          "API çalışıyor: <code>/api/docs</code>")
