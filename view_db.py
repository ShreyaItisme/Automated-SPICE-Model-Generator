import sqlite3

conn = sqlite3.connect(input("Enter database name") + ".db")
cur = conn.cursor()

print("=== COMPONENTS ===")
cur.execute("SELECT * FROM components")
for row in cur.fetchall():
    print(row)

print("\n=== ELECTRICAL SPECS ===")
cur.execute("SELECT * FROM electrical_specs")
for row in cur.fetchall():
    print(row)

conn.close()