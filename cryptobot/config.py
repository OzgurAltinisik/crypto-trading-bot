"""Loads config/bots.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .account import Sizing
from .strategy import build_strategy

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "bots.yaml"


@dataclass
class BotConfig:
    id: str
    symbol: str
    timeframe: str
    strategy_name: str
    params: dict
    enabled: bool = True
    initial_balance: float = 10_000.0
    fee: float = 0.001
    sizing: Sizing = field(default_factory=Sizing)
    strategy: object = field(init=False, repr=False)

    def __post_init__(self):
        self.strategy = build_strategy(self.strategy_name, self.params)


@dataclass
class AppConfig:
    exchange: str
    db_path: Path
    cache_dir: Path
    log_dir: Path
    tick_seconds: int
    bots: list[BotConfig]

    def bot(self, bot_id: str) -> BotConfig:
        for b in self.bots:
            if b.id == bot_id:
                return b
        raise KeyError(f"No bot '{bot_id}'. Available: {[b.id for b in self.bots]}")


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def load_config(path: Path = DEFAULT_CONFIG) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    bots = []
    seen = set()
    for b in raw["bots"]:
        if b["id"] in seen:
            raise ValueError(f"Duplicate bot id '{b['id']}'")
        seen.add(b["id"])
        bots.append(
            BotConfig(
                id=b["id"],
                symbol=b["symbol"],
                timeframe=b["timeframe"],
                strategy_name=b["strategy"],
                params=b.get("params", {}),
                enabled=b.get("enabled", True),
                initial_balance=b.get("initial_balance", defaults.get("initial_balance", 10_000.0)),
                fee=b.get("fee", defaults.get("fee", 0.001)),
                sizing=Sizing(
                    risk_per_trade=b.get("risk_per_trade", defaults.get("risk_per_trade")),
                    max_position=b.get("max_position", defaults.get("max_position", 1.0)),
                ),
            )
        )
    return AppConfig(
        exchange=raw.get("exchange", "binance"),
        db_path=_path(raw.get("db_path", "data/bot.db")),
        cache_dir=_path(raw.get("cache_dir", "data/cache")),
        log_dir=_path(raw.get("log_dir", "data/logs")),
        tick_seconds=raw.get("tick_seconds", 30),
        bots=bots,
    )
