import sqlite3
import pandas as pd

# Connect via standard DB-API or SQLAlchemy engine
conn = sqlite3.connect("components.db")

query = "SELECT part_number, gbw_mhz, slew_rate_v_us FROM component_specs"

# Read query output directly into a DataFrame
df = pd.read_sql_query(query, conn)

conn.close()

# Inspect and process data
print(df.head())
print(f"Average GBW: {df['gbw_mhz'].mean():.2f} MHz")