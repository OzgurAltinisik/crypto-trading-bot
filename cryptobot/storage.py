"""SQLite persistence: bot state (survives restarts), trades and signals.

The web API in phase 2 reads from the same database."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .position import Position

SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_state (
    bot_id          TEXT PRIMARY KEY,
    balance         REAL NOT NULL,
    position        TEXT,              -- JSON of Position, NULL when flat
    last_candle     TEXT,              -- open time (UTC) of last processed closed candle
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    entry_time      TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    exit_time       TEXT NOT NULL,
    exit_price      REAL NOT NULL,
    initial_stop    REAL,
    pnl_pct         REAL NOT NULL,
    pnl_usd         REAL NOT NULL,
    reason          TEXT NOT NULL,
    balance_after   REAL NOT NULL,
    qty             REAL,
    position_pct    REAL
);
CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    candle_time     TEXT NOT NULL,
    side            TEXT NOT NULL,     -- BUY / SELL
    price           REAL NOT NULL,
    acted           INTEGER NOT NULL,  -- 1 if it opened/closed a position
    created_at      TEXT NOT NULL,
    UNIQUE (bot_id, candle_time, side)
);
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades (bot_id, exit_time);
CREATE TABLE IF NOT EXISTS meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);
-- people who want alerts; one row per (channel, address)
CREATE TABLE IF NOT EXISTS subscribers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel         TEXT NOT NULL,       -- email / telegram
    address         TEXT NOT NULL,       -- e-mail address or telegram chat id
    token           TEXT NOT NULL UNIQUE,-- secret for confirm / manage / unsubscribe links
    bots            TEXT NOT NULL,       -- JSON list of bot ids
    events          TEXT NOT NULL,       -- 'all' (entries + exits) or 'entry'
    confirmed       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    confirmed_at    TEXT,
    confirm_sent_at TEXT,
    UNIQUE (channel, address)
);
-- messages waiting to be sent by the engine's sender thread
CREATE TABLE IF NOT EXISTS outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel         TEXT NOT NULL,
    address         TEXT NOT NULL,
    subject         TEXT,
    body_text       TEXT NOT NULL,
    body_html       TEXT,
    unsubscribe_url TEXT,
    dedupe_key      TEXT UNIQUE,         -- same alert is never queued twice
    created_at      TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    sent_at         TEXT,
    last_error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox (sent_at, next_attempt_at);
"""

MAX_SEND_ATTEMPTS = 6


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            # migrations for databases created by older versions
            cols = {r["name"] for r in c.execute("PRAGMA table_info(trades)")}
            for col in ("qty", "position_pct"):
                if col not in cols:
                    c.execute(f"ALTER TABLE trades ADD COLUMN {col} REAL")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # API can read while engine writes
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- bot state ---
    def load_state(self, bot_id: str, initial_balance: float) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT * FROM bot_state WHERE bot_id=?", (bot_id,)).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO bot_state (bot_id, balance, updated_at) VALUES (?,?,?)",
                    (bot_id, initial_balance, utcnow()),
                )
                return {"balance": initial_balance, "position": None, "last_candle": None}
        pos = Position.from_dict(json.loads(row["position"])) if row["position"] else None
        return {"balance": row["balance"], "position": pos, "last_candle": row["last_candle"]}

    def save_state(
        self, bot_id: str, balance: float, position: Optional[Position], last_candle: Optional[str]
    ) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE bot_state SET balance=?, position=?, last_candle=?, updated_at=? WHERE bot_id=?",
                (
                    balance,
                    json.dumps(position.to_dict()) if position else None,
                    last_candle,
                    utcnow(),
                    bot_id,
                ),
            )

    # --- trades & signals ---
    def save_trade(self, **t) -> None:
        cols = ", ".join(t)
        qs = ", ".join("?" for _ in t)
        with self._conn() as c:
            c.execute(f"INSERT INTO trades ({cols}) VALUES ({qs})", tuple(t.values()))

    def save_signal(self, bot_id: str, symbol: str, candle_time: str, side: str, price: float, acted: bool) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO signals (bot_id, symbol, candle_time, side, price, acted, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (bot_id, symbol, candle_time, side, price, int(acted), utcnow()),
            )

    # --- engine heartbeat (the dashboard shows whether the engine is alive) ---
    def heartbeat(self) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO meta (key, value) VALUES ('engine_heartbeat', ?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (utcnow(),))

    def last_heartbeat(self) -> Optional[str]:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key='engine_heartbeat'").fetchone()
        return row["value"] if row else None

    # --- reads for the API ---
    def all_states(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM bot_state").fetchall()
        out = {}
        for r in rows:
            out[r["bot_id"]] = {
                "balance": r["balance"],
                "position": json.loads(r["position"]) if r["position"] else None,
                "last_candle": r["last_candle"],
                "updated_at": r["updated_at"],
            }
        return out

    def trades(self, bot_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM trades", []
        if bot_id:
            q += " WHERE bot_id=?"
            args.append(bot_id)
        q += " ORDER BY exit_time DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def signals(self, bot_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        q, args = "SELECT * FROM signals", []
        if bot_id:
            q += " WHERE bot_id=?"
            args.append(bot_id)
        q += " ORDER BY candle_time DESC, id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args)]

    def trade_summary(self, bot_id: str) -> dict:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) net, "
                "COALESCE(SUM(pnl_pct > 0),0) wins FROM trades WHERE bot_id=?",
                (bot_id,),
            ).fetchone()
        return dict(row)

    def last_activity(self) -> dict:
        """Per bot: time of the last closed trade and the last signal (UTC ISO)."""
        out: dict = {}
        with self._conn() as c:
            for r in c.execute("SELECT bot_id, MAX(exit_time) t FROM trades GROUP BY bot_id"):
                out.setdefault(r["bot_id"], {})["last_exit"] = r["t"]
            for r in c.execute("SELECT bot_id, MAX(candle_time) t FROM signals GROUP BY bot_id"):
                out.setdefault(r["bot_id"], {})["last_signal"] = r["t"]
        return out

    # --- subscribers ---
    def get_subscriber(self, channel: str, address: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM subscribers WHERE channel=? AND address=?", (channel, address)).fetchone()
        return _sub(row)

    def subscriber_by_token(self, token: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM subscribers WHERE token=?", (token,)).fetchone()
        return _sub(row)

    def upsert_subscriber(self, channel: str, address: str, token: str, bots: list[str], events: str,
                          confirmed: bool = False) -> dict:
        """Create, or update the preferences of, a subscriber. An existing token and
        confirmation are kept."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO subscribers (channel, address, token, bots, events, confirmed, created_at, confirmed_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(channel, address) DO UPDATE SET bots=excluded.bots, events=excluded.events,"
                " confirmed=MAX(confirmed, excluded.confirmed),"
                " confirmed_at=COALESCE(confirmed_at, excluded.confirmed_at)",
                (channel, address, token, json.dumps(bots), events, int(confirmed), utcnow(),
                 utcnow() if confirmed else None),
            )
            row = c.execute("SELECT * FROM subscribers WHERE channel=? AND address=?", (channel, address)).fetchone()
        return _sub(row)

    def update_subscriber(self, token: str, **fields) -> Optional[dict]:
        if "bots" in fields:
            fields["bots"] = json.dumps(fields["bots"])
        if fields.get("confirmed"):
            fields["confirmed"] = 1
            fields.setdefault("confirmed_at", utcnow())
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE subscribers SET {sets} WHERE token=?", (*fields.values(), token))
            row = c.execute("SELECT * FROM subscribers WHERE token=?", (token,)).fetchone()
        return _sub(row)

    def delete_subscriber(self, token: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM subscribers WHERE token=?", (token,)).rowcount > 0

    def all_subscribers(self, confirmed_only: bool = True) -> list[dict]:
        q = "SELECT * FROM subscribers" + (" WHERE confirmed=1" if confirmed_only else "") + " ORDER BY id"
        with self._conn() as c:
            return [_sub(r) for r in c.execute(q)]

    def subscribers_for(self, bot_id: str, event: str) -> list[dict]:
        """Confirmed subscribers who want `event` ('entry' or 'exit') of `bot_id`."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM subscribers WHERE confirmed=1").fetchall()
        out = []
        for r in map(_sub, rows):
            if bot_id in r["bots"] and (r["events"] == "all" or event == "entry"):
                out.append(r)
        return out

    def count_subscribers(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT channel, COUNT(*) n FROM subscribers WHERE confirmed=1 GROUP BY channel").fetchall()
        return {r["channel"]: r["n"] for r in rows}

    # --- outbox ---
    def enqueue(self, channel: str, address: str, body_text: str, subject: Optional[str] = None,
                body_html: Optional[str] = None, unsubscribe_url: Optional[str] = None,
                dedupe_key: Optional[str] = None) -> bool:
        """Queue a message. Returns False if `dedupe_key` was queued before."""
        now = utcnow()
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO outbox (channel, address, subject, body_text, body_html, unsubscribe_url,"
                " dedupe_key, created_at, next_attempt_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (channel, address, subject, body_text, body_html, unsubscribe_url, dedupe_key, now, now),
            )
            return cur.rowcount > 0

    def due_messages(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM outbox WHERE sent_at IS NULL AND attempts < ? AND next_attempt_at <= ?"
                " ORDER BY id LIMIT ?",
                (MAX_SEND_ATTEMPTS, utcnow(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, msg_id: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE outbox SET sent_at=?, last_error=NULL WHERE id=?", (utcnow(), msg_id))

    def mark_failed(self, msg_id: int, error: str, retry_in_seconds: int) -> None:
        nxt = datetime.now(timezone.utc).timestamp() + retry_in_seconds
        with self._conn() as c:
            c.execute(
                "UPDATE outbox SET attempts=attempts+1, last_error=?, next_attempt_at=? WHERE id=?",
                (error[:500], datetime.fromtimestamp(nxt, timezone.utc).isoformat(timespec="seconds"), msg_id),
            )

    def prune_unconfirmed(self, days: int = 7) -> int:
        cutoff = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - days * 86400, timezone.utc)
        with self._conn() as c:
            return c.execute("DELETE FROM subscribers WHERE confirmed=0 AND created_at < ?",
                             (cutoff.isoformat(timespec="seconds"),)).rowcount

    def prune_outbox(self, days: int = 30) -> None:
        """Sent messages contain addresses; don't keep them longer than needed."""
        cutoff = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - days * 86400, timezone.utc)
        with self._conn() as c:
            c.execute("DELETE FROM outbox WHERE created_at < ?", (cutoff.isoformat(timespec="seconds"),))


def _sub(row) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    d["bots"] = json.loads(d["bots"])
    d["confirmed"] = bool(d["confirmed"])
    return d
