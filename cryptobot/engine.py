"""Live paper-trading engine: runs every enabled bot in one process.

* Signals come only from closed candles.
* State (balance, open position, last processed candle) is stored in SQLite
  after every change, so a restart continues where it left off.
* Stops/targets hit while the engine was offline are caught from the
  candles' highs/lows when it comes back.
"""
from __future__ import annotations

import html
import logging
import os
import signal
import time
from datetime import datetime, timezone

import pandas as pd

from .account import Event, PaperAccount
from .alerts import EmailSender, OutboxSender, queue_trade_alerts
from .config import AppConfig, BotConfig
from .data import fetch_closed_candles, make_exchange, timeframe_ms, with_retry
from .notifier import TelegramNotifier
from .storage import Storage

log = logging.getLogger(__name__)

REASONS_TR = {
    "STOP-LOSS": "Stop-loss",
    "TAKE-PROFIT": "Hedef",
    "SELL SIGNAL": "Satış sinyali",
    "BREAKEVEN STOP": "Başabaş stop",
    "TRAILING STOP": "İz süren stop",
}

FETCH_LIMIT = 1000          # Binance max per request; enough to warm up EMA200
CANDLE_CLOSE_GRACE_MS = 5_000


def fmt_price(p: float) -> str:
    return f"${p:,.2f}" if p >= 100 else f"${p:,.4f}"


def with_link(text: str) -> str:
    """Append a link to the dashboard (PUBLIC_URL, without the invite key)."""
    url = os.getenv("PUBLIC_URL")
    return text + (f'\n<a href="{html.escape(url)}">Paneli aç</a>' if url else "")


class LiveBot:
    def __init__(self, cfg: BotConfig, exchange, storage: Storage, notifier: TelegramNotifier):
        self.cfg = cfg
        self.exchange = exchange
        self.storage = storage
        self.notifier = notifier
        st = storage.load_state(cfg.id, cfg.initial_balance)
        self.account = PaperAccount(cfg.strategy, cfg.fee, st["balance"], st["position"], sizing=cfg.sizing)
        self.last_candle: str | None = st["last_candle"]
        self.tf_ms = timeframe_ms(cfg.timeframe)
        self.log = logging.getLogger(f"bot.{cfg.id}")

    # --- scheduling ---
    def candle_due(self, now_ms: int) -> bool:
        if self.last_candle is None:
            return True
        last_open = int(pd.Timestamp(self.last_candle).timestamp() * 1000)
        next_close = last_open + 2 * self.tf_ms
        return now_ms >= next_close + CANDLE_CLOSE_GRACE_MS

    def tick(self) -> None:
        now_ms = self.exchange.milliseconds()
        if self.candle_due(now_ms):
            self.process_candles()
        if self.account.position is not None:
            ticker = with_retry(self.exchange.fetch_ticker, self.cfg.symbol)
            now = datetime.now(timezone.utc)
            self.handle(self.account.on_price(now, float(ticker["last"])))

    # --- candle close ---
    def process_candles(self) -> None:
        df = fetch_closed_candles(self.exchange, self.cfg.symbol, self.cfg.timeframe, FETCH_LIMIT)
        if len(df) < self.cfg.strategy.warmup_bars:
            self.log.warning("Only %d candles, %d recommended for warm-up", len(df), self.cfg.strategy.warmup_bars)
        df = self.cfg.strategy.prepare(df)
        latest = df.index[-1].isoformat()
        if latest == self.last_candle:
            return  # exchange hasn't published the new candle yet

        if self.last_candle is None:
            new_bars = df.iloc[-1:]
        else:
            new_bars = df[df.index > pd.Timestamp(self.last_candle)]
            if len(new_bars) > 1:
                self.log.info("Catching up %d candles missed while offline", len(new_bars))

        for t, row in new_bars.iterrows():
            is_latest = t == df.index[-1]
            if self.account.position is not None and t <= pd.Timestamp(self.account.position.entry_time):
                continue
            # Only the newest candle may open a trade: a buy signal from hours
            # ago is stale. Missed candles still run stops/targets/sell signals.
            events = self.account.on_bar(t, row, allow_entry=is_latest)
            self.record_signals(t, row, events)
            self.handle(events)

        last = df.iloc[-1]
        extra = " ".join(
            f"{c} {last[c]:.2f}" for c in ("ema_fast", "ema_slow", "dc_high", "dc_low", "adx") if c in last
        )
        self.log.info(
            "%s close %s | %s | RSI %.1f | ATR %.2f | %s",
            df.index[-1].strftime("%Y-%m-%d %H:%M"), fmt_price(last["close"]), extra,
            last["rsi"], last["atr"], "IN POSITION" if self.account.position else "flat",
        )
        self.last_candle = latest
        self.persist()

    def record_signals(self, t, row, events: list[Event]) -> None:
        kinds = {e.kind for e in events}
        for side, flag in (("BUY", row["buy"]), ("SELL", row["sell"])):
            if flag:
                acted = ("open" in kinds) if side == "BUY" else any(
                    e.kind == "close" and e.trade.reason == "SELL SIGNAL" for e in events
                )
                self.storage.save_signal(self.cfg.id, self.cfg.symbol, t.isoformat(), side, float(row["close"]), acted)

    # --- events -> storage + telegram ---
    def persist(self) -> None:
        self.storage.save_state(self.cfg.id, self.account.balance, self.account.position, self.last_candle)

    def handle(self, events: list[Event]) -> None:
        if not events:
            return
        for e in events:
            if e.kind == "close":
                t = e.trade
                self.storage.save_trade(
                    bot_id=self.cfg.id, symbol=self.cfg.symbol, entry_time=t.entry_time,
                    entry_price=t.entry_price, exit_time=t.exit_time, exit_price=t.exit_price,
                    initial_stop=t.initial_stop, pnl_pct=t.pnl_pct, pnl_usd=t.pnl_usd,
                    reason=t.reason, balance_after=t.balance_after,
                    qty=t.qty, position_pct=t.position_pct,
                )
            self.persist()
            self.notifier.send(self.message(e))
            self.queue_alerts(e)
            self.log.info("%s %s", e.kind.upper(), e.trade.reason if e.trade else "")

    def queue_alerts(self, e: Event) -> None:
        """Subscriber alerts (e-mail / Telegram) go to the outbox; never break trading."""
        c = self.cfg
        try:
            if e.kind == "open":
                p = e.position
                queue_trade_alerts(self.storage, "entry", c.id, c.symbol, c.timeframe, p.entry_time,
                                   entry_price=p.entry_price, stop=p.stop)
            elif e.kind == "close":
                t = e.trade
                queue_trade_alerts(self.storage, "exit", c.id, c.symbol, c.timeframe, t.exit_time,
                                   entry_price=t.entry_price, exit_price=t.exit_price,
                                   pnl_pct=t.pnl_pct, reason=t.reason)
        except Exception:
            self.log.exception("Queueing subscriber alerts failed")

    def message(self, e: Event) -> str:
        c = self.cfg
        head = f"<b>{html.escape(c.symbol)}</b> · {c.timeframe} · <code>{html.escape(c.id)}</code>"
        p = e.position
        if e.kind == "open":
            lines = [
                "🟢 <b>AL sinyali — pozisyon açıldı</b>", head, "",
                f"Giriş : {fmt_price(p.entry_price)}",
                f"Stop  : {fmt_price(p.stop)} ({(p.stop / p.entry_price - 1) * 100:+.2f}%)",
            ]
            if p.take_profit:
                lines.append(f"Hedef : {fmt_price(p.take_profit)} ({(p.take_profit / p.entry_price - 1) * 100:+.2f}%)")
            if p.qty is not None:
                value = p.qty * p.entry_price
                risk = p.qty * (p.entry_price - p.stop * (1 - c.fee))
                lines.append(
                    f"Boyut : bakiyenin %{value / self.account.balance * 100:.0f}'i · "
                    f"stop'ta kayıp ${risk:,.0f} (%{risk / self.account.balance * 100:.1f})"
                )
            if p.breakeven_trigger:
                lines.append(f"Başabaş: {fmt_price(p.breakeven_trigger)}")
            lines += ["", "<i>Paper trading — yatırım tavsiyesi değildir.</i>"]
            return with_link("\n".join(lines))
        if e.kind == "breakeven":
            return "\n".join([
                "⚖️ <b>Başabaş stop aktif</b>", head, "",
                f"Stop {fmt_price(p.stop)} seviyesine taşındı (giriş {fmt_price(p.entry_price)}).",
            ])
        t = e.trade
        s = self.storage.trade_summary(c.id)
        emoji = "✅" if t.pnl_pct > 0 else "🔴"
        return with_link("\n".join([
            f"{emoji} <b>Pozisyon kapandı — {html.escape(REASONS_TR.get(t.reason, t.reason))}</b>", head, "",
            f"Giriş : {fmt_price(t.entry_price)}",
            f"Çıkış : {fmt_price(t.exit_price)}",
            f"K/Z   : {t.pnl_pct:+.2f}% (${t.pnl_usd:+,.2f})",
            f"Bakiye: ${t.balance_after:,.2f}",
            "",
            f"Toplam {s['n']} işlem · {s['wins']} kazanç · net ${s['net']:+,.2f}",
        ]))


class Engine:
    def __init__(self, config: AppConfig, notifier: TelegramNotifier):
        self.config = config
        self.exchange = make_exchange(config.exchange)
        self.storage = Storage(config.db_path)
        self.notifier = notifier
        self.bots = [LiveBot(b, self.exchange, self.storage, notifier) for b in config.bots if b.enabled]
        self.running = True
        self.outbox = OutboxSender(self.storage, EmailSender.from_env(), os.getenv("TELEGRAM_TOKEN") or None)
        self.commands = None
        if os.getenv("TELEGRAM_TOKEN"):
            from .telegram_bot import TelegramCommands
            self.commands = TelegramCommands.from_env(config, self.storage, notifier)

    def stop(self, *_):
        log.info("Shutdown requested")
        self.running = False

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        lines = ["🤖 <b>Motor başladı</b>", ""]
        for b in self.bots:
            pos = b.account.position
            lines.append(
                f"• <b>{html.escape(b.cfg.symbol)}</b> {b.cfg.timeframe} — "
                f"{html.escape(b.cfg.strategy.describe())}"
                + (f" — açık pozisyon {fmt_price(pos.entry_price)}" if pos else "")
            )
        self.notifier.send("\n".join(lines))
        if self.commands:
            self.commands.start()
        self.outbox.start()
        log.info("Running %d bots: %s", len(self.bots), ", ".join(b.cfg.id for b in self.bots))

        while self.running:
            started = time.monotonic()
            for bot in self.bots:
                try:
                    bot.tick()
                except Exception:
                    # One bot failing must not stop the others.
                    bot.log.exception("Tick failed")
            try:
                self.storage.heartbeat()
            except Exception:
                log.exception("Heartbeat failed")
            elapsed = time.monotonic() - started
            # sleep in small steps so Ctrl+C / SIGTERM is handled quickly
            end = time.monotonic() + max(0.0, self.config.tick_seconds - elapsed)
            while self.running and time.monotonic() < end:
                time.sleep(0.5)
        if self.commands:
            self.commands.stop()
        self.outbox.stop()
        for bot in self.bots:
            bot.persist()
        log.info("Stopped; state saved")
