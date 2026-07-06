import sqlite3
import pandas as pd

conn = sqlite3.connect("../data/trades.db")
df = pd.read_sql("SELECT * FROM islemler ORDER BY id ASC", conn)
conn.close()

print(f"Legacy records: {len(df)}\n")
print(df.to_string(index=False))