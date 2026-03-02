"""
nationality=TR olan tum kayitlari API'den cek,
DB'de all_nationalities alanini guncelle.
RabbitMQ'ya publish etmeden direkt SQLite yazar.
"""
import sys, time, sqlite3
sys.path.insert(0, '/tmp')
import interpol_client as _ic
InterpolClient = _ic.InterpolClient

client = InterpolClient('https://ws-public.interpol.int')
client._warmup_session()
url = 'https://ws-public.interpol.int/notices/v1/red'
h = client._build_headers(accept_json=True)
h['Referer'] = 'https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices'
h['Sec-Fetch-Site'] = 'same-site'
h['Sec-Fetch-Mode'] = 'cors'

conn = sqlite3.connect('/data/notices.db')

def fetch_all_for_nat(nat):
    results = {}
    page = 1
    while True:
        r = client._session.get(url, params={'nationality': nat, 'resultPerPage': 160, 'page': page},
                                headers=h, timeout=20)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} at page {page}, stopping")
            break
        data = r.json()
        items = data.get('_embedded', {}).get('notices', [])
        for n in items:
            eid = n.get('entity_id', '')
            nats = n.get('nationalities') or []
            all_nat = ','.join(nats) if nats else nat
            if eid:
                results[eid] = all_nat
        if 'next' not in data.get('_links', {}):
            break
        page += 1
        time.sleep(0.5)
    return results

print("TR nationality API taramasi basliyor...")
tr_api = fetch_all_for_nat('TR')
print(f"API'den {len(tr_api)} TR kaydi bulundu")
print()

# DB'deki TR kayitlari
db_tr = {r[0]: r[1] for r in conn.execute(
    "SELECT entity_id, all_nationalities FROM notices WHERE nationality='TR'"
).fetchall()}

# all_nationalities'i guncelle
updated = 0
inserted = 0
for eid, all_nat in tr_api.items():
    cur = conn.execute("SELECT id, nationality, all_nationalities FROM notices WHERE entity_id=?", (eid,))
    row = cur.fetchone()
    if row:
        # DB'de var, all_nationalities'i guncelle
        conn.execute("UPDATE notices SET all_nationalities=? WHERE entity_id=?", (all_nat, eid))
        if row[2] != all_nat:
            updated += 1
    # DB'de yok ise (henuz cekilmemis): sadece logla, publish etmiyoruz
    else:
        print(f"  DB'DE YOK: {eid} all_nationalities={all_nat}")
        inserted += 1

conn.commit()
print(f"Guncellenen: {updated}, DB'de Olmayan: {inserted}")
print()

# Sonuc: TR filtresinde kac kisi goruntuleniyor
db_now = conn.execute(
    "SELECT COUNT(1) FROM notices WHERE nationality='TR' OR all_nationalities LIKE '%TR%'"
).fetchone()[0]
print(f"Filtre sonrasi gorunen TR kayit sayisi: {db_now}")

# Yeni gorunenler kimler?
print()
print("Tum TR filtresinde gorunen kayitlar:")
rows = conn.execute(
    "SELECT entity_id, name, forename, nationality, all_nationalities FROM notices "
    "WHERE nationality='TR' OR all_nationalities LIKE '%TR%' ORDER BY name"
).fetchall()
for r in rows:
    print(f"  {r[0]:<20} {str(r[1]):<20} {str(r[2]):<20} nat={r[3]} all={r[4]}")
