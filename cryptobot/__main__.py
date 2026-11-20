"""Command line:

    python -m cryptobot run                      # start all enabled bots
    python -m cryptobot backtest btc_ema9_21_atr --start 2025-01-01 [--end ...] [--plot] [--save out.png]
    python -m cryptobot backtest all --start 2024-01-01
    python -m cryptobot optimize donchian_btc_4h  # walk-forward search, see config/optimize.yaml
    python -m cryptobot serve [--host 0.0.0.0] [--port 8000]   # web dashboard
    python -m cryptobot all                      # engine + dashboard in one process
    python -m cryptobot status                   # balances, open positions, last trades
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

from .config import DEFAULT_CONFIG, ROOT, load_config


def setup_logging(log_dir: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_dir / "engine.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.Formatter.converter = __import__("time").gmtime  # log times in UTC


def cmd_run(cfg, _args):
    from .engine import Engine
    from .notifier import TelegramNotifier

    setup_logging(cfg.log_dir)
    Engine(cfg, TelegramNotifier(os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))).run()


def cmd_backtest(cfg, args):
    from .backtest import format_report, plot, run_backtest

    setup_logging(None)
    bots = cfg.bots if args.bot == "all" else [cfg.bot(args.bot)]
    for b in bots:
        r = run_backtest(b, args.start, args.end, cache_dir=cfg.cache_dir)
        print(format_report(r))
        if args.trades:
            print(r.trades_frame().round(2).to_string(index=False))
        print()
        if args.plot or args.save:
            plot(r, args.save.replace("{id}", b.id) if args.save else None)


def cmd_optimize(cfg, args):
    import pandas as pd

    from .data import fetch_history, make_exchange
    from .optimize import expand_grid, load_experiments, summarize_walk_forward, walk_forward

    setup_logging(None)
    exps = load_experiments()
    names = list(exps) if args.name == "all" else [args.name]
    for name in names:
        if name not in exps:
            raise SystemExit(f"Unknown experiment '{name}'. Available: {list(exps)}")
        e = exps[name]
        combos = expand_grid(e.get("base", {}), e["grid"])
        # a year of extra history before the first window warms up every indicator
        since = pd.Timestamp(e["start"], tz="UTC") - pd.DateOffset(years=1)
        candles = fetch_history(make_exchange(cfg.exchange), e["symbol"], e["timeframe"], since,
                                cache_dir=cfg.cache_dir)
        print(f"===== {name}: {e['strategy']} {e['symbol']} {e['timeframe']} — {len(combos)} parameter sets =====")
        windows = walk_forward(
            candles, e["symbol"], e["timeframe"], e["strategy"], combos, e["start"],
            train_months=e["train_months"], test_months=e["test_months"], min_trades=e["min_trades"],
        )
        print(summarize_walk_forward(windows, list(e["grid"])))
        print()


def cmd_serve(cfg, args):
    import uvicorn

    from .api import create_app

    setup_logging(None)
    log_access_mode()
    # behind a reverse proxy (Caddy / Cloudflare Tunnel), trust its X-Forwarded-Proto/For so
    # redirects and cookies use https; FORWARDED_ALLOW_IPS="*" is set in docker-compose.yml
    uvicorn.run(create_app(cfg), host=args.host, port=args.port, log_level="warning",
                proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))


def cmd_all(cfg, args):
    """Engine + website in ONE process: for a home PC (with Cloudflare Tunnel) or a
    single-container host. The VPS uses separate containers (docker-compose.yml)."""
    import threading

    import uvicorn

    from .api import create_app
    from .engine import Engine
    from .notifier import TelegramNotifier

    setup_logging(cfg.log_dir)
    log_access_mode()
    server = uvicorn.Server(uvicorn.Config(
        create_app(cfg), host=args.host, port=args.port, log_level="warning",
        proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    ))
    web = threading.Thread(target=server.run, name="web", daemon=True)  # signals stay with the engine
    web.start()
    # don't run a bot nobody can see: wait for the website, stop if it can't start
    for _ in range(100):
        if server.started or not web.is_alive():
            break
        time.sleep(0.1)
    if not server.started:
        logging.getLogger(__name__).error(
            "Website could not start on port %d (already in use?). Stopping.", args.port)
        raise SystemExit(1)
    logging.getLogger(__name__).info("Website on http://%s:%d", args.host, args.port)
    try:
        Engine(cfg, TelegramNotifier(os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))).run()
    finally:
        server.should_exit = True
        web.join(timeout=5)


def log_access_mode():
    log = logging.getLogger(__name__)
    if os.getenv("DASHBOARD_KEY"):
        log.info("Invite-only site: share /?key=<DASHBOARD_KEY>")
    else:
        log.info("Public site (DASHBOARD_KEY empty)")


def cmd_test_alert(cfg, _args):
    """Queue a TEST message for every confirmed subscriber. The running engine
    sends it within a few seconds (same database), proving the whole chain works."""
    from datetime import datetime, timezone

    from .storage import Storage

    storage = Storage(cfg.db_path)
    subs = storage.all_subscribers(confirmed_only=True)
    if not subs:
        print("No subscribers yet. In Telegram send /abone btc to your bot, then run this again.")
        return
    names = {b.id: b.symbol.split("/")[0] for b in cfg.bots}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for sub in subs:
        coins = ", ".join(names.get(b, b) for b in sub["bots"])
        text = ("🧪 <b>Test bildirimi</b>\n"
                "Bu gerçek bir işlem değil; bildirim zinciri çalışıyor mu diye gönderildi.\n"
                f"Aboneliklerin: <b>{coins}</b>")
        if sub["channel"] == "telegram":
            storage.enqueue("telegram", sub["address"], text, dedupe_key=f"test:{sub['address']}:{stamp}")
        else:
            storage.enqueue("email", sub["address"], text.replace("<b>", "").replace("</b>", ""),
                            "Kripto Sinyal: test bildirimi", dedupe_key=f"test:{sub['address']}:{stamp}")
    print(f"Queued a test alert for {len(subs)} subscriber(s). The running engine sends it within ~5 seconds.")


def cmd_status(cfg, _args):
    if not cfg.db_path.exists():
        print("No database yet — start the engine first.")
        return
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    print("BOT STATE")
    for r in conn.execute("SELECT bot_id, balance, position IS NOT NULL open, last_candle, updated_at FROM bot_state"):
        print(f"  {r['bot_id']:<20} ${r['balance']:>11,.2f}  {'OPEN' if r['open'] else 'flat':<5} last candle {r['last_candle']}")
    print("\nLAST 10 TRADES")
    for r in conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 10"):
        print(f"  {r['exit_time'][:16]} {r['bot_id']:<20} {r['pnl_pct']:+6.2f}%  {r['reason']}")
    conn.close()


def main(argv=None):
    # Windows consoles default to a legacy code page; emojis/arrows need UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(prog="cryptobot")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="start the live paper-trading engine")
    bt = sub.add_parser("backtest", help="backtest a bot from config")
    bt.add_argument("bot", help="bot id from config, or 'all'")
    bt.add_argument("--start", default="2025-01-01")
    bt.add_argument("--end")
    bt.add_argument("--trades", action="store_true", help="print every trade")
    bt.add_argument("--plot", action="store_true")
    bt.add_argument("--save", help="save chart to file instead of showing it ({id} = bot id)")
    op = sub.add_parser("optimize", help="walk-forward parameter search (config/optimize.yaml)")
    op.add_argument("name", help="experiment name, or 'all'")
    sv = sub.add_parser("serve", help="start the web dashboard")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    al = sub.add_parser("all", help="engine + website in one process (home PC / single container)")
    al.add_argument("--host", default="127.0.0.1")
    al.add_argument("--port", type=int, default=8000)
    sub.add_parser("status", help="show balances and recent trades")
    sub.add_parser("test-alert", help="send a test alert to every subscriber (engine must be running)")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    {"run": cmd_run, "backtest": cmd_backtest, "optimize": cmd_optimize, "serve": cmd_serve, "all": cmd_all,
     "status": cmd_status, "test-alert": cmd_test_alert}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
