import ccxt
import pandas as pd
import requests
import time
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# --- Settings ---
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL           = "ETH/USDT"
TIMEFRAME        = "1h"
FEE              = 0.001
ATR_PERIOD       = 14
ATR_SL           = 2.0
ATR_TP           = 5.0
INITIAL_BALANCE  = 10000
BOT_NAME         = "EMA_9_21_ATR_ETH"
DB_PATH          = "../data/trades.db"

state = {
    "in_position" : False,
    "entry_price" : 0,
    "stop_price"  : 0,
    "tp_price"    : 0,
    "entry_time"  : None,
    "balance"     : INITIAL_BALANCE,
    "trade_count" : 0,
    "wins"        : 0,
    "losses"      : 0,
}

exchange = ccxt.binance()

def db_init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            bot           TEXT,
            symbol        TEXT,
            entry_time    TEXT,
            entry_price   REAL,
            exit_time     TEXT,
            exit_price    REAL,
            pnl_pct       REAL,
            pnl_usd       REAL,
            reason        TEXT,
            balance       REAL
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Database ready")

def db_save(entry_time, entry_price, exit_price, pnl_pct, pnl_usd, reason, balance):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades
        (bot, symbol, entry_time, entry_price, exit_time, exit_price,
         pnl_pct, pnl_usd, reason, balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        BOT_NAME, SYMBOL, str(entry_time), round(entry_price, 4),
        str(datetime.now()), round(exit_price, 4),
        round(pnl_pct, 2), round(pnl_usd, 2), reason, round(balance, 2)
    ))
    conn.commit()
    conn.close()
    print(f"[DB] Saved: {reason} | %{round(pnl_pct, 2)}")

def db_summary():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(pnl_usd), AVG(pnl_pct) FROM trades WHERE bot=?", (BOT_NAME,))
    row = c.fetchone()
    conn.close()
    return row

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        print("[Telegram] sent")
    except Exception as e:
        print(f"[Telegram ERROR] {e}")

def fetch_data():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=250)
    df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df["ema9"]   = df["close"].ewm(span=9,   adjust=False).mean()
    df["ema21"]  = df["close"].ewm(span=21,  adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss))
    df["hl"]  = df["high"] - df["low"]
    df["hc"]  = (df["high"] - df["close"].shift(1)).abs()
    df["lc"]  = (df["low"]  - df["close"].shift(1)).abs()
    df["tr"]  = df[["hl","hc","lc"]].max(axis=1)
    df["atr"] = df["tr"].ewm(alpha=1/ATR_PERIOD, adjust=False).mean()
    return df

def check_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    buy_signal  = (last["ema9"] > last["ema21"]) and (prev["ema9"] <= prev["ema21"]) and (last["rsi"] < 60) and (last["close"] > last["ema200"])
    sell_signal = (last["ema9"] < last["ema21"]) and (prev["ema9"] >= prev["ema21"]) and (last["rsi"] > 40)
    return buy_signal, sell_signal, last

def close_position(price, reason):
    exit_price = price * (1 - FEE)
    pnl_pct = (exit_price - state["entry_price"]) / state["entry_price"] * 100
    pnl_usd = state["balance"] * (pnl_pct / 100)
    state["balance"] += pnl_usd
    state["trade_count"] += 1
    if pnl_pct > 0:
        state["wins"] += 1
        emoji = "✅"
    else:
        state["losses"] += 1
        emoji = "❌"
    duration = datetime.now() - state["entry_time"]
    db_save(state["entry_time"], state["entry_price"], exit_price, pnl_pct, pnl_usd, reason, state["balance"])
    summary = db_summary()
    total_trades = summary[0] or 0
    total_pnl    = summary[1] or 0
    avg_pnl      = summary[2] or 0
    message = f"""
{emoji} <b>POSITION CLOSED — {reason}</b>

📈 Coin      : {SYMBOL}
🟢 Entry     : ${state['entry_price']:,.4f}
🔴 Exit      : ${exit_price:,.4f}
📊 PnL       : %{pnl_pct:.2f} (${pnl_usd:+,.2f})
⏱ Duration  : {duration.days}d {duration.seconds//3600}h
💰 Balance   : ${state['balance']:,.2f}

📋 Total     : {state['trade_count']} trades | ✅{state['wins']} ❌{state['losses']}
🗄 DB Summary: {total_trades} records | Net: ${total_pnl:+,.2f} | Avg: %{avg_pnl:.2f}
"""
    send_telegram(message)
    state["in_position"] = False
    state["entry_price"] = 0
    state["stop_price"]  = 0
    state["tp_price"]    = 0
    state["entry_time"]  = None

def check_signal_loop():
    try:
        df = fetch_data()
        buy_signal, sell_signal, last = check_signal(df)
        price = last["close"]
        atr   = last["atr"]
        timestamp = df.index[-1]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] "
              f"Price: ${price:,.2f} | "
              f"EMA9: ${last['ema9']:,.2f} | "
              f"EMA21: ${last['ema21']:,.2f} | "
              f"RSI: {last['rsi']:.1f} | "
              f"ATR: ${atr:,.2f} | "
              f"Position: {'YES' if state['in_position'] else 'NO'}")
        if not state["in_position"] and buy_signal:
            entry = price * (1 + FEE)
            stop  = entry - (atr * ATR_SL)
            tp    = entry + (atr * ATR_TP)
            state["entry_price"] = entry
            state["stop_price"]  = stop
            state["tp_price"]    = tp
            state["entry_time"]  = datetime.now()
            state["in_position"] = True
            message = f"""
🚀 <b>BUY SIGNAL — POSITION OPENED</b>

📈 Coin        : {SYMBOL}
💵 Entry       : ${entry:,.4f}
🛑 Stop-Loss   : ${stop:,.4f} (ATR×{ATR_SL})
🎯 Take-Profit : ${tp:,.4f} (ATR×{ATR_TP})
📐 RR Ratio    : 1:{round(ATR_TP/ATR_SL, 2)}
📊 RSI         : {last['rsi']:.1f}
📉 ATR         : ${atr:,.4f}
💰 Balance     : ${state['balance']:,.2f}
⏰ Time        : {timestamp}

⚠️ This is paper trading — no real order is placed!
"""
            send_telegram(message)
        elif state["in_position"] and sell_signal:
            close_position(price, "SELL SIGNAL")
    except Exception as e:
        print(f"[ERROR] {e}")

db_init()

send_telegram(f"""
🤖 <b>ETH EMA 9/21 + ATR Bot Started!</b>

💰 Initial balance : ${INITIAL_BALANCE:,}
📊 Strategy         : EMA 9/21 + ATR
⏱ Timeframe         : {TIMEFRAME}
🛑 ATR Stop          : ×{ATR_SL}
🎯 ATR TP            : ×{ATR_TP}
📐 RR                : 1:{round(ATR_TP/ATR_SL, 2)}
🗄 Logging           : SQLite (trades.db)
""")

print("ETH Bot running!")

check_counter = 0
while True:
    if state["in_position"]:
        try:
            ticker = exchange.fetch_ticker(SYMBOL)
            current_price = ticker["last"]
            if current_price <= state["stop_price"]:
                print(f"[STOP] ${current_price:,.2f}")
                close_position(current_price, "STOP-LOSS")
            elif current_price >= state["tp_price"]:
                print(f"[TP] ${current_price:,.2f}")
                close_position(current_price, "TAKE-PROFIT ✨")
        except Exception as e:
            print(f"[Error] {e}")
    if check_counter % 10 == 0:
        check_signal_loop()
    check_counter += 1
    time.sleep(30)