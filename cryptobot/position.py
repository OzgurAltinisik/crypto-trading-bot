"""Position bookkeeping shared by the live engine and the backtester."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from .strategy import Levels


@dataclass
class Position:
    entry_time: str           # ISO-8601 UTC
    entry_price: float        # fill price including the entry fee
    stop: float
    initial_stop: float
    take_profit: Optional[float] = None
    breakeven_trigger: Optional[float] = None
    breakeven_active: bool = False
    trail_distance: Optional[float] = None   # fixed at entry: ATR(entry) * trail_atr
    highest: Optional[float] = None          # highest price seen since entry
    trailed: bool = False                    # trailing stop has moved the stop
    qty: Optional[float] = None              # coins held; None = whole balance (v1 positions)

    @classmethod
    def open(cls, entry_time: str, price: float, fee: float, levels_fn) -> "Position":
        entry = price * (1 + fee)
        lv: Levels = levels_fn(entry)
        return cls(
            entry_time=entry_time,
            entry_price=entry,
            stop=lv.stop,
            initial_stop=lv.stop,
            take_profit=lv.take_profit,
            breakeven_trigger=lv.breakeven_trigger,
            trail_distance=lv.trail_distance,
            highest=price,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(**d)


@dataclass
class Exit:
    price: float   # raw market price before the exit fee
    reason: str


def check_exit(pos: Position, open_: float, high: float, low: float) -> Optional[Exit]:
    """Stop / target hit within a bar (or a single tick: open=high=low=price).

    If both are touched in the same bar the stop wins (conservative).
    A bar that opens through a level fills at the open (gap), not at the level.
    """
    if low <= pos.stop:
        if pos.trailed:
            reason = "TRAILING STOP"
        elif pos.breakeven_active:
            reason = "BREAKEVEN STOP"
        else:
            reason = "STOP-LOSS"
        return Exit(price=min(open_, pos.stop), reason=reason)
    if pos.take_profit is not None and high >= pos.take_profit:
        return Exit(price=max(open_, pos.take_profit), reason="TAKE-PROFIT")
    return None


def update_breakeven(pos: Position, high: float, fee: float) -> bool:
    """Move the stop to break-even (covering both fees) once the trigger is
    reached. Returns True only on the call that activates it."""
    if pos.breakeven_active or pos.breakeven_trigger is None:
        return False
    if high >= pos.breakeven_trigger:
        # exit at stop * (1 - fee) == entry_price  ->  zero PnL after fees
        pos.stop = max(pos.stop, pos.entry_price / (1 - fee))
        pos.breakeven_active = True
        return True
    return False


def update_trailing(pos: Position, high: float) -> bool:
    """Raise the stop to (highest high since entry - trail distance). Never lowers it.
    Returns True if the stop moved."""
    if pos.trail_distance is None:
        return False
    pos.highest = max(pos.highest or high, high)
    new_stop = pos.highest - pos.trail_distance
    if new_stop > pos.stop:
        pos.stop = new_stop
        pos.trailed = True
        return True
    return False


def pnl_pct(pos: Position, exit_price: float, fee: float) -> float:
    """Return of the trade in percent, after both fees."""
    net_exit = exit_price * (1 - fee)
    return (net_exit - pos.entry_price) / pos.entry_price * 100
