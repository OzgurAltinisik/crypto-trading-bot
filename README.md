# Crypto Trading Signal Bot

A multi-strategy crypto signal engine for Binance, built with Python. Strategies are prototyped in TradingView Pine Script, backtested on real Binance data and run live as paper-trading bots with Telegram alerts.

> ⚠️ **Paper trading only.** No real orders are placed. Educational project, not financial advice.

---

## How it works

```
config/bots.yaml ──► Strategy (indicators + buy/sell signals)
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
   Backtester                      Live engine (one process, all bots)
   history → PaperAccount          closed candles + ticker → PaperAccount
   metrics vs buy & hold           SQLite state/trades/signals → Telegram
```

The backtester and the live engine share the **same strategy and the same position logic** (`cryptobot/account.py`), and a test checks that they produce identical trades.

**Live engine guarantees**

- Signals are computed from **closed candles only**. The forming candle is dropped, so signals cannot appear and disappear mid-candle.
- Balance, open position and last processed candle are stored in SQLite after every change, so **a restart continues where it left off**.
- If the engine was offline, stops and targets that were hit in the meantime are found from the missed candles' highs and lows. Stale buy signals are not taken.
- 1000 candles of history are used, enough for EMA200 to converge, so live values match the backtest.
- RSI and ATR use Wilder smoothing, matching TradingView's `ta.rsi` / `ta.atr`.
- All times are in UTC. Logs go to stdout and a rotating file. One failing bot does not stop the others.

## Bots

| id | Pair | TF | Strategy |
|---|---|---|---|
| `btc_donchian_4h` | BTC/USDT | 4h | Donchian breakout: buy on a close above the 55-bar high while above EMA200; exit on a close below the 50-bar low or at the 2×ATR stop |
| `eth_donchian_4h` | ETH/USDT | 4h | same |
| `sol_donchian_4h` | SOL/USDT | 4h | same (weakest since 2025, under watch) |
| `btc_ema50_200` | BTC/USDT | 4h | EMA 50/200 cross, RSI < 70, 8% stop. Baseline. |
| `btc_ema9_21_atr`, `eth_ema9_21_atr` | 1h | | v1 strategies, **disabled**: they lost money out of sample |

To add a pair or change a parameter, edit `config/bots.yaml`. No code changes are needed.

## How the strategy was chosen

Picking the best backtest is easy to fool yourself with, so selection uses **walk-forward testing** (`python -m cryptobot optimize <experiment>`, grids in `config/optimize.yaml`):

1. Split 2019 → today into windows: 24 months of training, then the next 6 months of testing.
2. In each window, pick the best parameter set on the training part only (by Sharpe, with a minimum number of trades).
3. Trade that set on the test part, which the search never saw, and chain the test parts.

Out-of-sample results (2021-06 → 2026-11, 0.1% fee per side):

| Experiment | Out-of-sample | Buy & hold | Positive windows |
|---|---|---|---|
| Donchian BTC 4h | **+157%** | +102% | 8/11 |
| Donchian ETH 4h | **+186%** | −21% | 6/11 |
| Donchian SOL 4h (2023 →) | +162% | +751% | 6/8 |
| EMA trend BTC 4h | +27% | +102% | 6/11 |
| EMA 9/21 + ATR BTC 1h (v1) | −31% | +97% | 3/11 |
| EMA 9/21 + ATR ETH 1h (v1) | −34% | −24% | 4/11 |

The live Donchian parameters are **one shared set** for all three coins. The whole neighbourhood around it (exit 50, EMA200 filter, no trailing stop) scores well on BTC, ETH and SOL, so it is not a single lucky combination.

What we learned:
- **Trend following on 4h works on crypto; 1h EMA crossovers do not.** They trade too often and fees plus noise eat the edge.
- **A slow exit matters most.** A 50-bar exit beats 10 or 20. Trailing stops and fixed targets cut the big winners that pay for many small losses.
- **The EMA200 trend filter helps; ADX is neutral.**
- **The win rate is low (~25%).** Profits come from a few long trends, so expect long losing streaks.

## Position sizing

Every bot risks a fixed share of its balance per trade (`risk_per_trade` in `config/bots.yaml`, default 1.5%). The position size follows from the stop distance:

```
quantity = balance × risk_per_trade / (entry − stop)      capped at 100% of the balance (no leverage)
```

A wide stop gives a small position and a tight stop a larger one, so a stop-loss costs about the same in every trade (gaps can make it worse).

Sizing doesn't create profit; it is a dial between return and drawdown. Drawdown scales roughly linearly with the risk setting. BTC Donchian since 2021:

| Risk per trade | CAGR | Max drawdown | Avg position |
|---|---|---|---|
| whole balance (v1) | 20.9% | −51.9% | 100% |
| 0.5% | 6.6% | −7.6% | 18% |
| 1.0% | 12.6% | −14.3% | 37% |
| **1.5% (default)** | **16.7%** | **−20.1%** | **55%** |
| 2.0% | 20.2% | −24.9% | 70% |
| 3.0% | 23.6% | −34.5% | 87% |

At 2%, the bot earns almost the same as going all-in with half the drawdown. SOL runs at 1% because its recent edge is weak.

### Current bots (1.5% risk; SOL 1%; EMA 50/200 whole balance)

| Bot | Period | Return | Buy & hold | Max DD | B&H DD | Trades | PF |
|---|---|---|---|---|---|---|---|
| btc_donchian_4h | 2021-01 → 2026-11 | +147.0% | +152.7% | −20.1% | −77.0% | 65 | 2.26 |
| eth_donchian_4h | 2021-01 → 2026-11 | +268.5% | +178.6% | −18.3% | −81.1% | 62 | 2.70 |
| sol_donchian_4h | 2021-01 → 2026-11 | +375.6% | +5,194% | −25.5% | −96.6% | 66 | 3.53 |
| btc_donchian_4h | 2024-01 → 2026-11 | +56.8% | +74.8% | −15.7% | −53.4% | 35 | 2.07 |
| eth_donchian_4h | 2024-01 → 2026-11 | +67.1% | −8.7% | −18.3% | −68.0% | 30 | 2.42 |
| sol_donchian_4h | 2024-01 → 2026-11 | +10.4% | −17.7% | −15.6% | −78.5% | 35 | 1.46 |
| btc_ema50_200 | 2024-01 → 2026-11 | +77.6% | +74.8% | −29.9% | −53.4% | 12 | 2.04 |

The Donchian bots don't always beat buy & hold on return. What they offer is a similar or better return with a fraction of the drawdown: −15% to −25% instead of −50% to −95%.

The v1 9/21 strategies were only profitable in the v1 scripts because RSI was smoothed with a plain EMA instead of TradingView's Wilder method. `rsi_smoothing: ema` reproduces that.

## Usage

```bash
pip install -r requirements-dev.txt   # runtime + tests + charts
cp .env.example .env          # optional: TELEGRAM_TOKEN and TELEGRAM_CHAT_ID

python -m cryptobot backtest all --start 2025-01-01
python -m cryptobot backtest btc_donchian_4h --start 2024-01-01 --trades --plot
python -m cryptobot optimize donchian_btc_4h   # walk-forward parameter search
python -m cryptobot run       # start all enabled bots (Ctrl+C saves state and stops)
python -m cryptobot serve     # web dashboard on http://localhost:8000
python -m cryptobot status    # balances, open positions, last trades
python -m pytest              # tests
```

## Web dashboard

`python -m cryptobot serve` starts a read-only dashboard that works on phones too. The FastAPI backend serves the React frontend from `frontend/` (TypeScript, Tailwind CSS v4, shadcn project structure, TradingView Lightweight Charts, lucide icons, and the `ink-orbit-features` component for the "how it works" section). It shows:

- every bot with its live price, status, open P/L and paper balance,
- a candle chart with the strategy's channel/EMA lines, paper trades and backtest trades,
- backtest metrics with an equity curve against buy & hold,
- the latest signals and the trade history,
- whether the engine is running (heartbeat).

Build the frontend once (and after every UI change):

```bash
cd frontend
npm install
npm run build        # writes cryptobot/web/dist, served by `python -m cryptobot serve`
```

During UI work, run `python -m cryptobot serve` plus `npm run dev` in `frontend/` (Vite on :5173 with hot reload; `/api` is proxied to :8000).

The engine and the dashboard are separate processes that share `data/bot.db`, so everyone sees the same data.

**Sharing with friends:** set `DASHBOARD_KEY` in `.env` and send them `https://your-host/?key=<DASHBOARD_KEY>`. The key is stored in a cookie for 180 days and removed from the address bar. Without the key, visitors only see a "invite link required" page. The API is documented at `/api/docs`.

Without Telegram credentials, alerts are only written to the log. To get a token, talk to [@BotFather](https://t.me/BotFather). Your chat id is shown at `https://api.telegram.org/bot<TOKEN>/getUpdates`.

## Deployment

**Try it on your own Windows PC first (no server):** [docs/BILGISAYARDA.md](docs/BILGISAYARDA.md). `scripts\windows\kurulum.bat` sets everything up, and `scripts\windows\baslat.bat` runs the engine and the website in one process (`python -m cryptobot all`) and exposes them through a free Cloudflare quick tunnel.

**Permanent:**
`docker compose up -d --build` runs everything on a server: the engine, the dashboard and Caddy, which provides automatic HTTPS. The step-by-step guide (in Turkish) for a fresh Hetzner Ubuntu server is in **[docs/KURULUM.md](docs/KURULUM.md)**:

```bash
bash deploy/setup-server.sh   # Docker, firewall, swap, clone, .env, daily backup
docker compose up -d --build
bash deploy/update.sh         # later: backup, git pull, rebuild, restart
```

## Alerts for visitors

Visitors don't install anything. On the website they enter an e-mail address, pick bots and "entries only" or "entries + exits", and confirm through a double opt-in link. Every mail has a preferences link and RFC 8058 one-click unsubscribe. On Telegram they send `/abone btc`, `/abone hepsi alim` or `/iptal` to the public bot.

When a bot opens or closes a position, alerts are written to an `outbox` table. A sender thread in the engine delivers them over SMTP (any provider: Gmail app password without a domain, Brevo/Resend with one) and the Telegram API, with retries and de-duplication. Unconfirmed sign-ups are deleted after 7 days and sent-mail records after 30 days. The privacy notice is at `/gizlilik`.

## Project structure

```
cryptobot/
  indicators.py   EMA, Wilder RSI, ATR, ADX
  strategy.py     EmaCross + Donchian strategies, shared filters/exits
  position.py     stop / target / break-even / trailing rules
  account.py      PaperAccount: opens/closes positions (shared by live + backtest)
  data.py         Binance candles (closed only), pagination, CSV cache, retries
  storage.py      SQLite: bot_state, trades, signals
  engine.py       live engine
  backtest.py     backtester, metrics, charts
  optimize.py     walk-forward parameter search
  notifier.py     Telegram notifications
  telegram_bot.py Telegram commands (/abone, /iptal, /durum, ...)
  alerts.py       subscriber alerts: templates, SMTP, outbox sender
  api.py          FastAPI dashboard API + invite-key access, serves web/dist
frontend/         React + TypeScript + Tailwind dashboard (Vite)
  src/components/ui/   shadcn-style UI components (ink-orbit-features)
  src/components/      dashboard sections (bot cards, charts, backtest, trades)
config/bots.yaml  bot definitions
config/optimize.yaml  walk-forward experiments
tests/            unit + engine tests (fake exchange)
data/             bot.db, candle cache, logs (git-ignored)
```

## Roadmap

- [x] Phase 1: shared core engine, persistent state, closed-candle signals, backtest metrics
- [x] Phase 2: FastAPI + web dashboard (positions, chart with signals, trade history, equity) with invite-link sharing
- [x] Phase 3: Telegram channel + commands, Docker deployment on Hetzner (docs/KURULUM.md)
- [x] Public site with e-mail and Telegram alert subscriptions
- [ ] Phase 4: PWA with browser push, then optionally a native mobile app
- [x] Strategy work: ADX filter, trailing stop, Donchian breakout, walk-forward testing, SOL
- [x] Risk-based position sizing (1.5% of balance at risk per trade by default)
- [ ] One shared portfolio balance across bots (today each bot has its own paper balance)

## Tech stack

Python · ccxt · pandas · SQLite · FastAPI · React · TypeScript · Tailwind CSS · Vite · Lightweight Charts · matplotlib · Telegram Bot API · TradingView Pine Script · Hetzner Cloud

## License

MIT
