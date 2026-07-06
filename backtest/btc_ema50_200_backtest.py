import ccxt
import pandas as pd
import matplotlib.pyplot as plt

exchange = ccxt.binance()
print("Fetching BTC/USDT data...")

symbol    = "BTC/USDT"
timeframe = "4h"

all_data = []
since = exchange.parse8601("2023-01-01T00:00:00Z")

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
df["ema50"]  = df["close"].ewm(span=50,  adjust=False).mean()
df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

delta = df["close"].diff()
gain = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
df["rsi"] = 100 - (100 / (1 + gain / loss))

# --- Signals ---
df["buy"]  = (df["ema50"] > df["ema200"]) & (df["ema50"].shift(1) <= df["ema200"].shift(1))
df["sell"] = (df["ema50"] < df["ema200"]) & (df["ema50"].shift(1) >= df["ema200"].shift(1))

# --- Backtest ---
FEE             = 0.001
STOP_LOSS       = 0.08
INITIAL_BALANCE = 10000

in_position  = False
trades       = []
entry_price  = 0
entry_time   = None
stop_price   = 0
balance      = INITIAL_BALANCE
balance_log  = []

for i, row in df.iterrows():
    balance_log.append({"time": i, "balance": balance})

    if row["buy"] and not in_position:
        entry_price = row["close"] * (1 + FEE)
        entry_time  = i
        stop_price  = entry_price * (1 - STOP_LOSS)
        in_position = True

    elif in_position:
        if row["low"] <= stop_price:
            exit_price = stop_price * (1 - FEE)
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            pnl_usd = balance * (pnl_pct / 100)
            balance += pnl_usd
            trades.append({
                "Entry Time": entry_time, "Entry $": round(entry_price, 2),
                "Exit Time": i, "Exit $": round(exit_price, 2),
                "PnL %": round(pnl_pct, 2), "PnL USD": round(pnl_usd, 2),
                "Reason": "STOP-LOSS"
            })
            in_position = False

        elif row["sell"]:
            exit_price = row["close"] * (1 - FEE)
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            pnl_usd = balance * (pnl_pct / 100)
            balance += pnl_usd
            trades.append({
                "Entry Time": entry_time, "Entry $": round(entry_price, 2),
                "Exit Time": i, "Exit $": round(exit_price, 2),
                "PnL %": round(pnl_pct, 2), "PnL USD": round(pnl_usd, 2),
                "Reason": "SELL SIGNAL"
            })
            in_position = False

balance_df = pd.DataFrame(balance_log).set_index("time")

# --- Results ---
print("\n===== BTC/USDT BACKTEST (EMA 50/200) =====")
if trades:
    results = pd.DataFrame(trades)
    wins    = results[results["PnL %"] > 0]
    losses  = results[results["PnL %"] <= 0]

    print(f"Initial balance     : ${INITIAL_BALANCE:,.2f}")
    print(f"Final balance       : ${balance:,.2f}")
    print(f"Net profit          : ${balance - INITIAL_BALANCE:,.2f}")
    print(f"Total return        : %{round((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100, 2)}")
    print(f"────────────────────────────────────")
    print(f"Total trades        : {len(results)}")
    print(f"Winning trades      : {len(wins)} (%{round(len(wins)/len(results)*100, 1)})")
    print(f"Losing trades       : {len(losses)}")
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

ax1.plot(df.index, df["close"],  color="white",  linewidth=0.8, label="BTC Price")
ax1.plot(df.index, df["ema50"],  color="cyan",   linewidth=1.2, label="EMA 50")
ax1.plot(df.index, df["ema200"], color="orange", linewidth=1.2, label="EMA 200")

buy_df  = df[df["buy"]]
sell_df = df[df["sell"]]
ax1.scatter(buy_df.index,  buy_df["close"],  marker="^", color="lime", s=100, label="BUY",  zorder=5)
ax1.scatter(sell_df.index, sell_df["close"], marker="v", color="red",  s=100, label="SELL", zorder=5)

ax1.set_facecolor("#131722")
ax1.legend(loc="upper left", fontsize=8)
ax1.set_title(f"BTC/USDT 4H | EMA 50/200 | Stop-Loss: %{STOP_LOSS*100}", color="white")
ax1.tick_params(colors="white")

ax2.plot(df.index, df["rsi"], color="violet", linewidth=0.8, label="RSI")
ax2.axhline(70, color="red",  linestyle="--", linewidth=0.8, alpha=0.6)
ax2.axhline(30, color="lime", linestyle="--", linewidth=0.8, alpha=0.6)
ax2.set_facecolor("#131722")
ax2.set_ylabel("RSI", color="white")
ax2.tick_params(colors="white")
ax2.legend(fontsize=8)

ax3.plot(balance_df.index, balance_df["balance"], color="gold", linewidth=1.2, label="Balance")
ax3.axhline(INITIAL_BALANCE, color="gray", linestyle="--", linewidth=0.8, alpha=0.6, label=f"Start ${INITIAL_BALANCE:,}")
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