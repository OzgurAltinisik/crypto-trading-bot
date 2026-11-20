"""Alerts for subscribers (e-mail and Telegram).

Flow: something happens (a bot opens/closes a position, someone signs up)
-> messages are written to the `outbox` table -> the engine's `OutboxSender`
thread sends them, with retries. Writing first and sending later means a slow
or failing mail server never blocks trading, and the web process can queue
mails (confirmations) that the engine process sends.

E-mail goes out over plain SMTP, so any provider works:
  - now, without a domain: a dedicated Gmail account + app password
  - later, with a domain: Brevo, Resend, Postmark, Amazon SES ... (only .env changes)
"""
from __future__ import annotations

import html
import logging
import os
import secrets
import smtplib
import ssl
import threading
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Callable, Optional

import requests

from .storage import Storage

log = logging.getLogger(__name__)

REASONS_TR = {
    "STOP-LOSS": "Stop-loss",
    "TAKE-PROFIT": "Hedef",
    "SELL SIGNAL": "Satış sinyali",
    "BREAKEVEN STOP": "Başabaş stop",
    "TRAILING STOP": "İz süren stop",
}
EVENTS = {"all": "alım + satım", "entry": "sadece alımlar"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def public_url() -> str:
    return os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")


def manage_url(token: str) -> str:
    return f"{public_url()}/abonelik?token={token}"


def unsubscribe_url(token: str) -> str:
    """One-click unsubscribe endpoint (RFC 8058 List-Unsubscribe-Post)."""
    return f"{public_url()}/api/subscriptions/unsubscribe?token={token}"


def fmt_price(p: float) -> str:
    return f"${p:,.2f}" if p >= 100 else f"${p:,.4f}"


# ----------------------------------------------------------------- templates
def _email_html(title: str, lines: list[str], button: Optional[tuple[str, str]], footer: str) -> str:
    """Small, inline-styled HTML mail in the dashboard's ink style."""
    body = "".join(f'<p style="margin:0 0 10px">{l}</p>' for l in lines)
    btn = ""
    if button:
        btn = (f'<p style="margin:22px 0"><a href="{html.escape(button[1])}" style="background:#151515;color:#f5f5f5;'
               f'padding:11px 18px;text-decoration:none;font-weight:600;display:inline-block">{html.escape(button[0])}</a></p>')
    return f"""<!doctype html><html lang="tr"><body style="margin:0;background:#efefef;padding:24px 12px;
font-family:Manrope,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#151515">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">
<table role="presentation" width="100%" style="max-width:520px;background:#fbfbfb;border:1px solid #e2e2e2" cellspacing="0" cellpadding="0">
<tr><td style="padding:22px 24px 6px;font-size:13px;color:#7b7b7b">◆ Kripto Sinyal</td></tr>
<tr><td style="padding:6px 24px 4px"><h1 style="font-size:20px;margin:0 0 14px;letter-spacing:-.02em">{html.escape(title)}</h1>
<div style="font-size:15px;line-height:1.55">{body}</div>{btn}</td></tr>
<tr><td style="padding:16px 24px 22px;border-top:1px solid #e2e2e2;font-size:12px;line-height:1.5;color:#7b7b7b">{footer}</td></tr>
</table></td></tr></table></body></html>"""


def _footer(token: str) -> tuple[str, str]:
    m, u = manage_url(token), unsubscribe_url(token)
    text = (f"Tercihlerini değiştir: {m}\nAbonelikten çık: {u}\n\n"
            "Paper trading — gerçek emir verilmez, yatırım tavsiyesi değildir.")
    htm = (f'<a href="{html.escape(m)}" style="color:#3d3d3d">Tercihlerini değiştir</a> · '
           f'<a href="{html.escape(u)}" style="color:#3d3d3d">Abonelikten çık</a><br>'
           "Paper trading — gerçek emir verilmez, yatırım tavsiyesi değildir.")
    return text, htm


@dataclass
class Rendered:
    subject: str
    text: str
    html: str
    telegram: str


def render_trade_alert(kind: str, symbol: str, timeframe: str, bot_id: str, *, entry_price: float,
                       stop: Optional[float] = None, exit_price: Optional[float] = None,
                       pnl_pct: Optional[float] = None, reason: Optional[str] = None,
                       token: str = "") -> Rendered:
    """kind = 'entry' or 'exit'."""
    link = f"{public_url()}/?bot={bot_id}"
    if kind == "entry":
        subject = f"🟢 {symbol} botu işleme girdi — {fmt_price(entry_price)}"
        title = f"{symbol} botu işleme girdi"
        lines = [f"Giriş fiyatı: <b>{fmt_price(entry_price)}</b>"]
        if stop:
            lines.append(f"Stop: {fmt_price(stop)} ({(stop / entry_price - 1) * 100:+.2f}%)")
    else:
        emoji = "✅" if (pnl_pct or 0) > 0 else "🔴"
        subject = f"{emoji} {symbol} botu pozisyonu kapattı — {pnl_pct:+.2f}%"
        title = f"{symbol} botu pozisyonu kapattı"
        lines = [
            f"Sebep: {html.escape(REASONS_TR.get(reason or '', reason or ''))}",
            f"Giriş {fmt_price(entry_price)} → çıkış {fmt_price(exit_price or 0)}",
            f"Sonuç: <b>{pnl_pct:+.2f}%</b>",
        ]
    lines.append(f'<span style="color:#7b7b7b">{html.escape(timeframe)} · {html.escape(bot_id)}</span>')
    ft, fh = _footer(token)
    plain = "\n".join(l.replace("<b>", "").replace("</b>", "") for l in lines[:-1])
    text = f"{title}\n\n{plain}\n\nPanel: {link}\n\n{ft}"
    tg = f"<b>{html.escape(title)}</b>\n" + "\n".join(lines[:-1]) + f'\n<a href="{html.escape(link)}">Panelde gör</a>'
    return Rendered(subject, text, _email_html(title, lines, ("Panelde gör", link), fh), tg)


def render_confirmation(token: str, bots: list[str], events: str, bot_names: dict[str, str]) -> Rendered:
    url = f"{public_url()}/api/subscriptions/confirm?token={token}"
    names = ", ".join(bot_names.get(b, b) for b in bots)
    title = "Aboneliğini onayla"
    lines = [
        "Kripto Sinyal botlarından bildirim almak için kaydoldun (ya da biri bu adresi girdi).",
        f"Botlar: <b>{html.escape(names)}</b> · {EVENTS.get(events, events)}",
        "Onaylamazsan sana hiç bildirim gelmez ve adresin 7 gün içinde silinir.",
    ]
    text = (f"{title}\n\nBotlar: {names} ({EVENTS.get(events, events)})\n\nOnaylamak için: {url}\n\n"
            "Bu isteği sen yapmadıysan bu maili yok say.")
    ft = "Bu isteği sen yapmadıysan bu maili yok sayabilirsin."
    return Rendered("Kripto Sinyal: aboneliğini onayla", text, _email_html(title, lines, ("Aboneliği onayla", url), ft), "")


def render_manage_link(token: str) -> Rendered:
    title = "Abonelik tercihlerin"
    lines = ["Bu adres zaten abone. Botları veya bildirim türünü aşağıdaki linkten değiştirebilirsin."]
    ft, fh = _footer(token)
    text = f"{title}\n\n{lines[0]}\n\n{manage_url(token)}\n\n{ft}"
    return Rendered("Kripto Sinyal: abonelik tercihlerin", text,
                    _email_html(title, lines, ("Tercihleri aç", manage_url(token)), fh), "")


# ------------------------------------------------------------------ queueing
def queue_trade_alerts(storage: Storage, kind: str, bot_id: str, symbol: str, timeframe: str,
                       event_time: str, **details) -> int:
    """Queue an alert for every confirmed subscriber of `bot_id` who wants `kind`.
    `event_time` makes the dedupe key, so a restart never sends the same alert twice."""
    n = 0
    for sub in storage.subscribers_for(bot_id, kind):
        r = render_trade_alert(kind, symbol, timeframe, bot_id, token=sub["token"], **details)
        key = f"{sub['channel']}:{sub['address']}:{bot_id}:{kind}:{event_time}"
        if sub["channel"] == "email":
            ok = storage.enqueue("email", sub["address"], r.text, r.subject, r.html,
                                 unsubscribe_url(sub["token"]), dedupe_key=key)
        else:
            ok = storage.enqueue("telegram", sub["address"], r.telegram, dedupe_key=key)
        n += ok
    if n:
        log.info("Queued %d %s alert(s) for %s", n, kind, bot_id)
    return n


# ------------------------------------------------------------------- senders
class EmailSender:
    """SMTP with STARTTLS (port 587) or implicit TLS (465)."""

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, sender_name: str = "Kripto Sinyal"):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.sender_name = sender, sender_name

    @classmethod
    def from_env(cls) -> Optional["EmailSender"]:
        host = os.getenv("SMTP_HOST")
        if not host:
            return None
        user = os.getenv("SMTP_USER", "")
        return cls(host, int(os.getenv("SMTP_PORT", "587")), user, os.getenv("SMTP_PASSWORD", ""),
                   os.getenv("MAIL_FROM", user), os.getenv("MAIL_FROM_NAME", "Kripto Sinyal"))

    def build(self, to: str, subject: str, text: str, html_body: Optional[str], unsub: Optional[str]) -> EmailMessage:
        m = EmailMessage()
        m["From"] = formataddr((self.sender_name, self.sender))
        m["To"] = to
        m["Subject"] = subject
        m["Message-ID"] = make_msgid(domain=self.sender.split("@")[-1])
        if unsub:
            m["List-Unsubscribe"] = f"<{unsub}>"
            m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        m.set_content(text)
        if html_body:
            m.add_alternative(html_body, subtype="html")
        return m

    def send(self, msg: EmailMessage) -> None:
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as s:
                s.starttls(context=ctx)
                if self.user:
                    s.login(self.user, self.password)
                s.send_message(msg)


class OutboxSender:
    """Background thread in the engine: sends queued messages with exponential backoff."""

    def __init__(self, storage: Storage, email: Optional[EmailSender], telegram_token: Optional[str],
                 interval: float = 5.0, telegram_post: Optional[Callable] = None):
        self.storage = storage
        self.email = email
        self.telegram_token = telegram_token
        self.interval = interval
        self.telegram_post = telegram_post or requests.post
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if not email:
            log.info("E-mail alerts off (SMTP_HOST empty); Telegram only")

    def send_one(self, m: dict) -> None:
        if m["channel"] == "email":
            if not self.email:
                raise RuntimeError("e-mail not configured")
            self.email.send(self.email.build(m["address"], m["subject"] or "", m["body_text"],
                                             m["body_html"], m["unsubscribe_url"]))
        elif m["channel"] == "telegram":
            if not self.telegram_token:
                raise RuntimeError("telegram not configured")
            r = self.telegram_post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                data={"chat_id": m["address"], "text": m["body_text"], "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            body = r.json() if hasattr(r, "json") else {}
            if not body.get("ok", False):
                # the user blocked the bot or deleted the chat: stop sending to them
                desc = str(body.get("description", ""))
                if "blocked" in desc or "chat not found" in desc or "deactivated" in desc:
                    sub = self.storage.get_subscriber("telegram", m["address"])
                    if sub:
                        self.storage.delete_subscriber(sub["token"])
                raise RuntimeError(f"telegram: {desc or r.status_code}")
        else:
            raise RuntimeError(f"unknown channel {m['channel']}")

    def run_once(self) -> int:
        sent = 0
        for m in self.storage.due_messages():
            if m["channel"] == "email" and not self.email:
                continue  # leave it queued until SMTP is configured
            try:
                self.send_one(m)
                self.storage.mark_sent(m["id"])
                sent += 1
            except Exception as e:
                retry = min(3600, 30 * 2 ** m["attempts"])
                log.warning("Sending %s #%d failed (%s), retry in %ds", m["channel"], m["id"], e, retry)
                self.storage.mark_failed(m["id"], str(e), retry)
        return sent

    def _loop(self) -> None:
        last_prune = 0.0
        while not self._stop.is_set():
            try:
                self.run_once()
                if time.monotonic() - last_prune > 6 * 3600:
                    # privacy: drop old sent mails and never-confirmed sign-ups
                    self.storage.prune_outbox(days=30)
                    self.storage.prune_unconfirmed(days=7)
                    last_prune = time.monotonic()
            except Exception:
                log.exception("Outbox loop failed")
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="outbox-sender", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
