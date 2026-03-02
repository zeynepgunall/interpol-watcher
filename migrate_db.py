import sqlite3

conn = sqlite3.connect('/data/notices.db')
cur = conn.cursor()

# Sutun zaten var mi kontrol et
cur.execute("PRAGMA table_info(notices)")
cols = [row[1] for row in cur.fetchall()]
print("Mevcut sutunlar:", cols)

if 'all_nationalities' not in cols:
    cur.execute("ALTER TABLE notices ADD COLUMN all_nationalities TEXT DEFAULT NULL")
    conn.commit()
    print("DONE: all_nationalities sutunu eklendi")
else:
    print("SKIP: all_nationalities zaten var")

# Mevcut nationality degerlerini all_nationalities'e kopyala (null olanlari doldur)
cur.execute("""
    UPDATE notices
    SET all_nationalities = nationality
    WHERE all_nationalities IS NULL AND nationality IS NOT NULL
""")
conn.commit()
print(f"Updated {conn.total_changes} rows with existing nationality values")

# Dogrulama
cur.execute("SELECT COUNT(1) FROM notices WHERE all_nationalities IS NOT NULL")
print("all_nationalities dolu olan:", cur.fetchone()[0])
