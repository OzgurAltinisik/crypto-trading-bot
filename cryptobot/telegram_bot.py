"""Telegram commands, answered by the engine process (long polling, no webhook).

    /durum                 engine status, price and state of every bot
    /pozisyonlar           open positions with unrealised P/L
    /islemler              last closed trades
    /abone btc [alim]      alerts when the BTC bot trades ('alim' = entries only)
    /abone hepsi           alerts from every bot
    /iptal btc | /iptal    stop alerts from one bot / from all
    /aboneliklerim         current subscriptions
    /botlar                bot list
    /panel                 link to the web dashboard
    /yardim                this list

TELEGRAM_PUBLIC=1 (default): anyone may use the bot. TELEGRAM_PUBLIC=0: only
chats in TELEGRAM_CHAT_ID / TELEGRAM_ALLOWED_CHATS; anyone else is told their
chat id, so the owner can add it.
"""
from __future__ import annotations

import html
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

import requests

from . import alerts
from .config import AppConfig
from .notifier import TelegramNotifier
from .storage import Storage

log = logging.getLogger(__name__)

COMMANDS = [
    ("durum", "Botların durumu: /durum ya da /durum btc"),
    ("abone", "Bildirim al: /abone btc, /abone hepsi alim"),
    ("iptal", "Bildirimi durdur: /iptal btc, /iptal"),
    ("aboneliklerim", "Aboneliklerin"),
    ("pozisyonlar", "Açık pozisyonlar"),
    ("islemler", "Son kapanan işlemler"),
    ("botlar", "Bot listesi"),
    ("panel", "Web panelinin linki"),
    ("yardim", "Komut listesi"),
]
ALIASES = {"start": "yardim", "help": "yardim", "status": "durum", "positions": "pozisyonlar", "trades": "islemler",
           "subscribe": "abone", "unsubscribe": "iptal", "stop": "iptal"}
ALL_WORDS = {"hepsi", "tumu", "tümü", "tum", "tüm", "all"}
ENTRY_WORDS = {"alim", "alım", "giris", "giriş", "entry"}


def fmt_price(p: Optional[float]) -> str:
    if p is None:
        return "—"
    return f"${p:,.2f}" if p >= 100 else f"${p:,.4f}"


def ago_tr(iso: Optional[str]) -> str:
    if not iso:
        return "henüz yok"
    secs = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds())
    if secs < 3600:
        return f"{int(secs // 60)} dk önce"
    if secs < 86400:
        return f"{int(secs // 3600)} saat önce"
    return f"{int(secs // 86400)} gün önce"


def parse_command(text: str) -> Optional[str]:
    """'/Durum@MyBot arg' -> 'durum'; None for non-commands."""
    if not text or not text.startswith("/"):
        return None
    cmd = text.split()[0][1:].split("@")[0].lower()
    return ALIASES.get(cmd, cmd)


def parse_args(text: str) -> list[str]:
    return [a.lower() for a in text.split()[1:]]


class TelegramCommands:
    def __init__(
        self,
        token: str,
        config: AppConfig,
        storage: Storage,
        notifier: TelegramNotifier,
        allowed_chats: set[str],
        public_url: Optional[str] = None,
        prices: Optional[Callable[[list[str]], dict]] = None,
        public: bool = True,
    ):
        self.token = token
        self.config = config
        self.storage = storage
        self.notifier = notifier
        self.allowed = {c.strip() for c in allowed_chats if c and c.strip()}
        self.public_url = public_url
        self.public = public
        self.prices = prices or self._fetch_prices
        self.bots = [b for b in config.bots if b.enabled]
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._exchange = None

    @classmethod
    def from_env(cls, config: AppConfig, storage: Storage, notifier: TelegramNotifier) -> "TelegramCommands":
        allowed = {os.getenv("TELEGRAM_CHAT_ID", "")}
        allowed |= set(os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(","))
        return cls(os.getenv("TELEGRAM_TOKEN", ""), config, storage, notifier, allowed, os.getenv("PUBLIC_URL"),
                   public=os.getenv("TELEGRAM_PUBLIC", "1") != "0")

    # ---------------- answers (pure, testable) ----------------
    def respond(self, cmd: str, args: Optional[list[str]] = None, chat_id: str = "") -> str:
        args = args or []
        if cmd == "yardim":
            return "\n".join(
                ["<b>Kripto Sinyal botu</b>", "Botlar işleme girince/çıkınca sana haber verebilirim.", ""]
                + [f"/{c} — {d}" for c, d in COMMANDS]
                + ["", "<i>Paper trading — yatırım tavsiyesi değildir.</i>"]
            )
        if cmd == "abone":
            return self._subscribe(chat_id, args)
        if cmd == "iptal":
            return self._unsubscribe(chat_id, args)
        if cmd == "aboneliklerim":
            return self._my_subscriptions(chat_id)
        if cmd == "botlar":
            return "\n".join(["<b>Botlar</b>"] + [
                f"• <b>{html.escape(self._coin(b))}</b> — {html.escape(b.symbol)} {b.timeframe} · <code>{html.escape(b.id)}</code>"
                for b in self.bots
            ] + ["", "Abone olmak için: /abone btc (ya da bot kodu)"])
        if cmd in ("durum", "pozisyonlar"):
            bots = self._select(args)
            if bots is None:
                coins = ", ".join(sorted({self._coin(b).lower() for b in self.bots}))
                return f"Bu coin için bot yok. Botlar: {coins}\nÖrnek: /{cmd} btc ya da /{cmd}"
            return self._status(bots) if cmd == "durum" else self._positions(bots)
        if cmd == "islemler":
            return self._trades()
        if cmd == "panel":
            return f'<a href="{html.escape(self.public_url)}">Paneli aç</a>' if self.public_url else "Panel adresi (PUBLIC_URL) ayarlanmamış."
        return "Bu komutu tanımıyorum. /yardim yaz."

    # ---------------- subscriptions ----------------
    @staticmethod
    def _coin(bot) -> str:
        return bot.symbol.split("/")[0]

    def _resolve(self, words: list[str]) -> Optional[list[str]]:
        """['btc'] -> first enabled BTC bot; ['hepsi'] -> all; bot ids work too. None if unknown."""
        names = [w for w in words if w not in ENTRY_WORDS]
        if not names:
            return None
        if any(w in ALL_WORDS for w in names):
            return [b.id for b in self.bots]
        ids = []
        for w in names:
            bot = next((b for b in self.bots if b.id.lower() == w), None) or \
                next((b for b in self.bots if self._coin(b).lower() == w), None)
            if bot is None:
                return None
            ids.append(bot.id)
        return list(dict.fromkeys(ids))

    def _select(self, words: list[str]):
        """Bots to *show*: no argument or 'hepsi' -> all; 'btc' -> every BTC bot; a bot id -> that bot."""
        if not words or any(w in ALL_WORDS for w in words):
            return list(self.bots)
        picked = [b for b in self.bots if b.id.lower() in words or self._coin(b).lower() in words]
        return picked or None

    def _names(self, ids: list[str]) -> str:
        by_id = {b.id: b for b in self.bots}
        return ", ".join(f"{self._coin(by_id[i])} ({by_id[i].timeframe})" for i in ids if i in by_id) or "—"

    def _subscribe(self, chat_id: str, args: list[str]) -> str:
        ids = self._resolve(args)
        if ids is None:
            coins = ", ".join(sorted({self._coin(b).lower() for b in self.bots}))
            return f"Hangi bot? Örnek: /abone btc · /abone hepsi · /abone eth alim\nBotlar: {coins}"
        existing = self.storage.get_subscriber("telegram", chat_id)
        bots = list(dict.fromkeys((existing["bots"] if existing else []) + ids))
        if any(a in ENTRY_WORDS for a in args):
            events = "entry"
        else:
            events = existing["events"] if existing else "all"
        self.storage.upsert_subscriber("telegram", chat_id, alerts.new_token(), bots, events, confirmed=True)
        return (f"✅ Abone oldun: <b>{html.escape(self._names(bots))}</b>\n"
                f"Bildirim: {alerts.EVENTS[events]}\n\n"
                "Değiştirmek için /abone eth alim, durdurmak için /iptal btc ya da /iptal")

    def _unsubscribe(self, chat_id: str, args: list[str]) -> str:
        existing = self.storage.get_subscriber("telegram", chat_id)
        if not existing:
            return "Zaten bir aboneliğin yok."
        ids = self._resolve(args) if args else [b.id for b in self.bots]
        if ids is None:
            return "Hangi bot? Örnek: /iptal btc · tümü için sadece /iptal"
        left = [i for i in existing["bots"] if i not in ids]
        if not left:
            self.storage.delete_subscriber(existing["token"])
            return "🔕 Tüm bildirimler durduruldu. Tekrar başlamak için /abone btc"
        self.storage.update_subscriber(existing["token"], bots=left)
        return f"🔕 Durduruldu. Kalan abonelikler: <b>{html.escape(self._names(left))}</b>"

    def _my_subscriptions(self, chat_id: str) -> str:
        sub = self.storage.get_subscriber("telegram", chat_id)
        if not sub:
            return "Henüz abone değilsin. Örnek: /abone btc"
        return (f"<b>Aboneliklerin</b>\n{html.escape(self._names(sub['bots']))}\n"
                f"Bildirim: {alerts.EVENTS.get(sub['events'], sub['events'])}")

    def _status(self, bots=None) -> str:
        bots = bots if bots is not None else self.bots
        states = self.storage.all_states()
        activity = self.storage.last_activity()
        prices = self.prices(sorted({b.symbol for b in bots}))
        hb = self.storage.last_heartbeat()
        if hb:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb)).total_seconds()
            engine = "🟢 Motor çalışıyor" if age < 180 else f"🔴 Motor {int(age // 60)} dk'dır sessiz"
        else:
            engine = "🔴 Motor henüz çalışmadı"
        lines = [f"<b>{engine}</b>", ""]
        for b in bots:
            st = states.get(b.id, {})
            pos = st.get("position")
            price = prices.get(b.symbol)
            bal = st.get("balance", b.initial_balance)
            ret = (bal / b.initial_balance - 1) * 100
            state = "Pozisyonda" if pos else "Beklemede"
            if pos and price:
                state += f" ({(price * (1 - b.fee) / pos['entry_price'] - 1) * 100:+.2f}%)"
            lines.append(f"<b>{html.escape(b.symbol)}</b> {b.timeframe} · {fmt_price(price)}")
            lines.append(f"   {state} · bakiye ${bal:,.0f} ({ret:+.1f}%)")
            last = max(filter(None, [pos["entry_time"] if pos else None, activity.get(b.id, {}).get("last_exit")]), default=None)
            lines.append(f"   Son işlem: {ago_tr(last)}")
        if len(bots) < len(self.bots):
            lines += ["", "Bildirim almak için: /abone " + self._coin(bots[0]).lower()]
        return "\n".join(lines)

    def _positions(self, bots=None) -> str:
        bots = bots if bots is not None else self.bots
        states = self.storage.all_states()
        open_bots = [(b, states[b.id]["position"]) for b in bots if states.get(b.id, {}).get("position")]
        if not open_bots:
            return "Açık pozisyon yok. Bot sinyal bekliyor." if len(bots) == 1 else "Açık pozisyon yok. Botlar sinyal bekliyor."
        prices = self.prices(sorted({b.symbol for b, _ in open_bots}))
        lines = ["<b>Açık pozisyonlar</b>"]
        for b, p in open_bots:
            price = prices.get(b.symbol)
            pnl = f"{(price * (1 - b.fee) / p['entry_price'] - 1) * 100:+.2f}%" if price else "—"
            lines += [
                "",
                f"<b>{html.escape(b.symbol)}</b> {b.timeframe} · K/Z <b>{pnl}</b>",
                f"   Giriş {fmt_price(p['entry_price'])} · şimdi {fmt_price(price)}",
                f"   Stop {fmt_price(p['stop'])}" + (f" · hedef {fmt_price(p['take_profit'])}" if p.get("take_profit") else ""),
                f"   Açılış {p['entry_time'][:16].replace('T', ' ')} UTC",
            ]
        return "\n".join(lines)

    def _trades(self, n: int = 5) -> str:
        ids = {b.id for b in self.bots}
        rows = [t for t in self.storage.trades(limit=50) if t["bot_id"] in ids][:n]
        if not rows:
            return "Henüz kapanmış işlem yok."
        lines = [f"<b>Son {len(rows)} işlem</b>"]
        for t in rows:
            emoji = "✅" if t["pnl_pct"] > 0 else "🔴"
            lines.append(f"{emoji} {html.escape(t['symbol'])} {t['pnl_pct']:+.2f}% (${t['pnl_usd']:+,.0f}) · {t['exit_time'][:10]}")
        return "\n".join(lines)

    def _fetch_prices(self, symbols: list[str]) -> dict:
        try:
            if self._exchange is None:
                from .data import make_exchange
                self._exchange = make_exchange(self.config.exchange)  # own instance: not shared across threads
            t = self._exchange.fetch_tickers(symbols)
            return {s: t[s]["last"] for s in symbols if s in t}
        except Exception:
            log.exception("Price fetch for Telegram failed")
            return {}

    # ---------------- updates ----------------
    def handle_update(self, update: dict) -> Optional[tuple[str, str]]:
        """Returns (chat_id, reply) or None. Channel posts and non-commands are ignored."""
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return None
        text = msg.get("text", "")
        cmd = parse_command(text)
        if not cmd:
            return None
        chat_id = str(msg["chat"]["id"])
        if not self.public and chat_id not in self.allowed:
            return chat_id, (
                "Bu botu kullanma iznin yok.\n"
                f"Sohbet kimliğin: <code>{chat_id}</code>\n"
                "Erişim için bu numarayı panelin sahibine gönder."
            )
        return chat_id, self.respond(cmd, parse_args(text), chat_id)

    def _api(self, method: str, **params):
        r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=40)
        r.raise_for_status()
        return r.json().get("result")

    def _loop(self) -> None:
        offset = None
        try:
            self._api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
            # skip whatever was sent while the engine was down
            backlog = self._api("getUpdates", offset=-1, timeout=0) or []
            offset = backlog[-1]["update_id"] + 1 if backlog else None
        except Exception:
            log.exception("Telegram command setup failed")
        while not self._stop.is_set():
            try:
                updates = self._api("getUpdates", offset=offset, timeout=25, allowed_updates=["message"]) or []
                for u in updates:
                    offset = u["update_id"] + 1
                    out = self.handle_update(u)
                    if out:
                        self.notifier.send(out[1], chat_id=out[0])
            except Exception as e:
                log.warning("Telegram polling error: %s", e)
                self._stop.wait(5)

    def start(self) -> None:
        if not self.token:
            return
        self._thread = threading.Thread(target=self._loop, name="telegram-commands", daemon=True)
        self._thread.start()
        log.info("Telegram commands enabled (%s)", "public" if self.public else f"{len(self.allowed)} chat(s)")

    def stop(self) -> None:
        self._stop.set()
