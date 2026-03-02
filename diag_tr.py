import sqlite3

conn = sqlite3.connect('/data/notices.db')

# Multi-nationality sorunu: nationality='TR' olmayan ama nationalities json'inda TR gecenler
# Web consumer notice'i kaydederken nationality alanina nationalities[0] yaziyor
# Eger nationalities=[XX, TR] ise DB'ye XX olarak kaydediliyor

# Tum kayitlarda nationality alanini gosterelim
result = conn.execute("""
    SELECT nationality, COUNT(1) as cnt
    FROM notices
    WHERE nationality IS NOT NULL
    GROUP BY nationality
    ORDER BY cnt DESC
    LIMIT 20
""").fetchall()
print("Top 20 nationality DB'de:")
for nat, cnt in result:
    print(f"  {nat}: {cnt}")

print()
print("TR kayitlari toplami:", conn.execute(
    "SELECT COUNT(1) FROM notices WHERE nationality='TR'"
).fetchone()[0])
