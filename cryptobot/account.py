"""Paper-trading account: the single place where positions are opened and
closed. The backtester feeds it historical bars; the live engine feeds it
closed bars plus ticker prices between bars. Same rules either way."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .position import Position, check_exit, pnl_pct, update_breakeven, update_trailing


@dataclass
class Trade:
    entry_time: str
    entry_price: float     # incl. entry fee
    exit_time: str
    exit_price: float      # raw market price; fee is applied in pnl
    initial_stop: float
    pnl_pct: float
    pnl_usd: float
    reason: str
    balance_after: float
    qty: Optional[float] = None
    position_pct: Optional[float] = None   # position value as % of balance at entry


@dataclass
class Sizing:
    """How much of the balance goes into a trade.

    risk_per_trade: fraction of the balance lost if the initial stop is hit
        (0.01 = 1%). The position is sized so that stop distance × quantity
        equals that amount: wide stop -> small position, tight stop -> larger.
        None = put the whole balance in every trade (v1 behaviour).
    max_position: cap on the position value as a fraction of the balance
        (1.0 = never more than the balance, i.e. no leverage).
    """
    risk_per_trade: Optional[float] = None
    max_position: float = 1.0

    def __post_init__(self):
        if self.risk_per_trade is not None and not 0 < self.risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be in (0, 1]")
        if not 0 < self.max_position <= 1:
            raise ValueError("max_position must be in (0, 1] (no leverage)")

    def quantity(self, balance: float, entry_price: float, stop: float, fee: float) -> float:
        cap = balance * self.max_position / entry_price
        if self.risk_per_trade is None:
            return cap
        loss_per_unit = entry_price - stop * (1 - fee)
        if loss_per_unit <= 0:
            return cap
        return min(cap, balance * self.risk_per_trade / loss_per_unit)


@dataclass
class Event:
    kind: str                         # "open" | "close" | "breakeven"
    position: Optional[Position] = None
    trade: Optional[Trade] = None


def _iso(t) -> str:
    return pd.Timestamp(t).isoformat()


class PaperAccount:
    def __init__(self, strategy, fee: float, balance: float, position: Optional[Position] = None,
                 sizing: Optional[Sizing] = None):
        self.strategy = strategy
        self.fee = fee
        self.balance = balance          # cash; equals equity while flat
        self.position = position
        self.sizing = sizing or Sizing()

    def qty(self, pos: Position) -> float:
        # positions saved before sizing existed used the whole balance
        return pos.qty if pos.qty is not None else self.balance / pos.entry_price

    def equity(self, price: float) -> float:
        """Balance if the open position were sold at `price` now."""
        if self.position is None:
            return self.balance
        return self.balance + self.qty(self.position) * (price * (1 - self.fee) - self.position.entry_price)

    def open(self, time, price: float, row: pd.Series) -> Event:
        assert self.position is None
        pos = Position.open(_iso(time), price, self.fee, lambda entry: self.strategy.levels(entry, row))
        pos.qty = self.sizing.quantity(self.balance, pos.entry_price, pos.stop, self.fee)
        self.position = pos
        return Event("open", position=pos)

    def close(self, time, price: float, reason: str) -> Event:
        pos = self.position
        assert pos is not None
        pct = pnl_pct(pos, price, self.fee)
        qty = self.qty(pos)
        position_pct = qty * pos.entry_price / self.balance * 100
        usd = qty * (price * (1 - self.fee) - pos.entry_price)
        self.balance += usd
        self.position = None
        return Event(
            "close",
            position=pos,
            trade=Trade(
                entry_time=pos.entry_time,
                entry_price=pos.entry_price,
                exit_time=_iso(time),
                exit_price=price,
                initial_stop=pos.initial_stop,
                pnl_pct=pct,
                pnl_usd=usd,
                reason=reason,
                balance_after=self.balance,
                qty=qty,
                position_pct=position_pct,
            ),
        )

    def on_bar(self, time, row: pd.Series, allow_entry: bool = True) -> list[Event]:
        """Process one closed bar (row from strategy.prepare()).

        Order: stop/target within the bar -> break-even / trailing update -> sell signal at the
        close -> buy signal at the close (never on the bar we just exited)."""
        events: list[Event] = []
        if self.position is not None:
            ex = check_exit(self.position, row["open"], row["high"], row["low"])
            if ex:
                events.append(self.close(time, ex.price, ex.reason))
                return events
            if update_breakeven(self.position, row["high"], self.fee):
                events.append(Event("breakeven", position=self.position))
            update_trailing(self.position, row["high"])   # applies from the next bar on
            if row["sell"]:
                events.append(self.close(time, row["close"], "SELL SIGNAL"))
                return events
        elif allow_entry and row["buy"]:
            events.append(self.open(time, row["close"], row))
        return events

    def on_price(self, time, price: float) -> list[Event]:
        """Live ticker price between bar closes: only checks stop / target.
        Break-even and trailing stops move at bar close only, exactly as in the
        backtest, so live and backtested trades stay identical."""
        events: list[Event] = []
        if self.position is None:
            return events
        ex = check_exit(self.position, price, price, price)
        if ex:
            events.append(self.close(time, ex.price, ex.reason))
        return events
