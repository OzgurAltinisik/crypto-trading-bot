import ccxt
import pandas as pd
import matplotlib.pyplot as plt

exchange = ccxt.binance()
print("Fetching ETH/USDT data...")

symbol    = "ETH/USDT"
timeframe = "1h"

all_data = []
since = exchange.parse8601("2025-01-01T00:00:00Z")

while True:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
    if not ohlcv:
        break
    all_data += ohlcv
    since = ohlcv[-1][0] + 1
    if len(ohlcv) < 1000:
        break

df = pd.DataFrame(all_data, columns=["timestamp","open","high","low","close","volume"])
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
df.set_index("timestamp", inplace=True)
df = df[~df.index.duplicated()]

print(f"Data fetched: {len(df)} candles | {df.index[0]} - {df.index[-1]}")

# --- Indicators ---
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
df["atr"] = df["tr"].ewm(alpha=1/14, adjust=False).mean()

# --- Signals ---
df["buy"]  = (df["ema9"] > df["ema21"]) & (df["ema9"].shift(1) <= df["ema21"].shift(1)) & (df["rsi"] < 60) & (df["close"] > df["ema200"])
df["sell"] = (df["ema9"] < df["ema21"]) & (df["ema9"].shift(1) >= df["ema21"].shift(1)) & (df["rsi"] > 40)

# --- Backtest ---
FEE             = 0.001
ATR_SL          = 2.0
ATR_TP          = 5.0
INITIAL_BALANCE = 10000

in_position  = False
trades       = []
entry_price  = 0
entry_time   = None
stop_price   = 0
tp_price     = 0
balance      = INITIAL_BALANCE
balance_log  = []

for i, row in df.iterrows():
    balance_log.append({"time": i, "balance": balance})

    if row["buy"] and not in_position:
        entry_price = row["close"] * (1 + FEE)
        entry_time  = i
        stop_price  = entry_price - (row["atr"] * ATR_SL)
        tp_price    = entry_price + (row["atr"] * ATR_TP)
        in_position = True

    elif in_position:
        if row["low"] <= stop_price:
            exit_price = stop_price * (1 - FEE)
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            pnl_usd = balance * (pnl_pct / 100)
            balance += pnl_usd
            trades.append({
                "Entry Time": entry_time, "Entry $": round(entry_price, 4),
                "Exit Time": i, "Exit $": round(exit_price, 4),
                "PnL %": round(pnl_pct, 2), "PnL USD": round(pnl_usd, 2),
                "Reason": "STOP-LOSS"
            })
            in_position = False

        elif row["high"] >= tp_price:
            exit_price = tp_price * (1 - FEE)
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            pnl_usd = balance * (pnl_pct / 100)
            balance += pnl_usd
            trades.append({
                "Entry Time": entry_time, "Entry $": round(entry_price, 4),
                "Exit Time": i, "Exit $": round(exit_price, 4),
                "PnL %": round(pnl_pct, 2), "PnL USD": round(pnl_usd, 2),
                "Reason": "TAKE-PROFIT"
            })
            in_position = False

        elif row["sell"]:
            exit_price = row["close"] * (1 - FEE)
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            pnl_usd = balance * (pnl_pct / 100)
            balance += pnl_usd
            trades.append({
                "Entry Time": entry_time, "Entry $": round(entry_price, 4),
                "Exit Time": i, "Exit $": round(exit_price, 4),
                "PnL %": round(pnl_pct, 2), "PnL USD": round(pnl_usd, 2),
                "Reason": "SELL SIGNAL"
            })
            in_position = False

balance_df = pd.DataFrame(balance_log).set_index("time")

# --- Results ---
print("\n===== ETH/USDT BACKTEST (EMA 9/21 + ATR, no breakeven) =====")
if trades:
    results = pd.DataFrame(trades)
    wins    = results[results["PnL %"] > 0]
    losses  = results[results["PnL %"] <= 0]
    stops   = results[results["Reason"] == "STOP-LOSS"]
    tps     = results[results["Reason"] == "TAKE-PROFIT"]
    sells   = results[results["Reason"] == "SELL SIGNAL"]

    print(f"Initial balance     : ${INITIAL_BALANCE:,.2f}")
    print(f"Final balance       : ${balance:,.2f}")
    print(f"Net profit          : ${balance - INITIAL_BALANCE:,.2f}")
    print(f"Total return        : %{round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 2)}")
    print(f"────────────────────────────────────")
    print(f"Total trades        : {len(results)}")
    print(f"Winning trades      : {len(wins)} (%{round(len(wins)/len(results)*100, 1)})")
    print(f"Losing trades       : {len(losses)}")
    print(f"Stop-loss           : {len(stops)}")
    print(f"Take-profit         : {len(tps)}")
    print(f"Sell signal         : {len(sells)}")
    print(f"────────────────────────────────────")
    print(f"Average PnL         : %{round(results['PnL %'].mean(), 2)}")
    print(f"Best trade          : %{results['PnL %'].max()}")
    print(f"Worst trade         : %{results['PnL %'].min()}")
    print(f"\n--- Trade List ---")
    print(results.to_string(index=False))
else:
    print("No signals occurred.")

# --- Chart ---
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 11), sharex=False,
                                     gridspec_kw={"height_ratios": [3, 1, 1.5]})

ax1.plot(df.index, df["close"],  color="white",  linewidth=0.8, label="ETH Price")
ax1.plot(df.index, df["ema9"],   color="lime",   linewidth=1.2, label="EMA 9")
ax1.plot(df.index, df["ema21"],  color="orange", linewidth=1.2, label="EMA 21")
ax1.plot(df.index, df["ema200"], color="cyan",   linewidth=1.0, label="EMA 200")

buy_df  = df[df["buy"]]
sell_df = df[df["sell"]]
ax1.scatter(buy_df.index,  buy_df["close"],  marker="^", color="lime", s=80, label="BUY",  zorder=5)
ax1.scatter(sell_df.index, sell_df["close"], marker="v", color="red",  s=80, label="SELL", zorder=5)

if trades:
    for _, row in results.iterrows():
        color = "lime" if row["PnL %"] > 0 else "red"
        ax1.scatter(row["Exit Time"], row["Exit $"], marker="x", color=color, s=60, zorder=6)

ax1.set_facecolor("#131722")
ax1.legend(loc="upper left", fontsize=8)
ax1.set_title(f"ETH/USDT 1H | EMA 9/21 + ATR (SL×{ATR_SL} / TP×{ATR_TP})", color="white")
ax1.tick_params(colors="white")

ax2.plot(df.index, df["rsi"], color="violet", linewidth=0.8, label="RSI")
ax2.axhline(60, color="red",  linestyle="--", linewidth=0.8, alpha=0.6)
ax2.axhline(40, color="lime", linestyle="--", linewidth=0.8, alpha=0.6)
ax2.set_facecolor("#131722")
ax2.set_ylabel("RSI", color="white")
ax2.tick_params(colors="white")
ax2.legend(fontsize=8)

ax3.plot(balance_df.index, balance_df["balance"], color="gold", linewidth=1.2, label="Balance")
ax3.axhline(INITIAL_BALANCE, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
ax3.fill_between(balance_df.index, INITIAL_BALANCE, balance_df["balance"],
                 where=balance_df["balance"] >= INITIAL_BALANCE, alpha=0.2, color="lime")
ax3.fill_between(balance_df.index, INITIAL_BALANCE, balance_df["balance"],
                 where=balance_df["balance"] <  INITIAL_BALANCE, alpha=0.2, color="red")
ax3.set_facecolor("#131722")
ax3.set_ylabel("Balance ($)", color="white")
ax3.tick_params(colors="white")
ax3.legend(fontsize=8)

fig.patch.set_facecolor("#131722")
plt.tight_layout()
plt.show()