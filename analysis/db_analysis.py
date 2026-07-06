import sqlite3
import pandas as pd

pd.set_option("display.width", 150)
pd.set_option("display.max_columns", None)

conn = sqlite3.connect("../data/trades.db")
df = pd.read_sql("SELECT * FROM trades ORDER BY id ASC", conn)
conn.close()

if len(df) == 0:
    print("No trades recorded yet.")
else:
    print(f"Total records: {len(df)}\n")

    print("===== SUMMARY BY BOT =====")
    summary = df.groupby("bot").agg(
        trade_count=("id", "count"),
        total_pnl_usd=("pnl_usd", "sum"),
        avg_pnl_pct=("pnl_pct", "mean"),
        best_pct=("pnl_pct", "max"),
        worst_pct=("pnl_pct", "min"),
        winning_trades=("pnl_pct", lambda x: (x > 0).sum())
    )
    summary["win_rate_pct"] = round(summary["winning_trades"] / summary["trade_count"] * 100, 1)
    summary = summary.round(2)
    print(summary)

    print("\n===== EXIT REASON BREAKDOWN (by bot) =====")
    reason_breakdown = df.groupby(["bot", "reason"]).size().unstack(fill_value=0)
    print(reason_breakdown)

    print("\n===== LAST 15 TRADES =====")
    print(df[["bot","symbol","entry_time","exit_time","pnl_pct","pnl_usd","reason","balance"]].tail(15).to_string(index=False))

    print("\n===== WORST 10 TRADES =====")
    worst = df.nsmallest(10, "pnl_pct")
    print(worst[["bot","symbol","entry_time","exit_time","pnl_pct","pnl_usd","reason"]].to_string(index=False))

    print("\n===== BEST 10 TRADES =====")
    best = df.nlargest(10, "pnl_pct")
    print(best[["bot","symbol","entry_time","exit_time","pnl_pct","pnl_usd","reason"]].to_string(index=False))