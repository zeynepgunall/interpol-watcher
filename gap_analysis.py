"""
Gap v3: HIGH_COUNT_NATS x tum AW - cap arama + genis ornekleme
"""
import sys, time, sqlite3, random
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

def total(params):
    r = client._session.get(url, params={**params, 'resultPerPage': 1, 'page': 1}, headers=h, timeout=15)
    if r.status_code == 200:
        return r.json().get('total', 0)
    return f'HTTP_{r.status_code}'

def fetch_ids(params):
    ids, page = [], 1
    while True:
        r = client._session.get(url, params={**params, 'resultPerPage': 160, 'page': page}, headers=h, timeout=20)
        if r.status_code != 200:
            break
        d = r.json()
        items = d.get('_embedded', {}).get('notices', [])
        ids.extend(n['entity_id'] for n in items if 'entity_id' in n)
        if len(items) < 160 or d.get('total', 0) <= page * 160:
            break
        page += 1
        time.sleep(0.5)
    return ids

conn = sqlite3.connect('/data/notices.db')
db_ids = set(r[0] for r in conn.execute('SELECT entity_id FROM notices').fetchall())
print(f"DB total: {len(db_ids)}, API total: {total({})}")

NATS = _ic.InterpolClient.ALL_NATIONALITIES
ALL_HIGH = ['RU', 'SV', 'IN', 'AR', 'PK', 'GT']

# == 1. HIGH × ALL_AW: hangi kombinasyon 160'i asiyor? ==
print(f"\n=== HIGH × ALL AW cap taramasi ({len(ALL_HIGH)*2*len(NATS)} sorgu) ===")
capped = []
for nat in ALL_HIGH:
    for sex in ['M', 'F']:
        for aw in NATS:
            t = total({'sexId': sex, 'nationality': nat, 'arrestWarrantCountryId': aw})
            if isinstance(t, int) and t > 160:
                capped.append({'sex': sex, 'nat': nat, 'aw': aw, 'total': t})
                print(f"  CAP: sex={sex} nat={nat} aw={aw} total={t}")
            time.sleep(0.12)

if not capped:
    print("  Hic cap yok! Bunlar sorun degil.")
else:
    print(f"\n{len(capped)} capped kombinasyon bulundu. Entity ID'ler aliniyor...")
    missing_total = []
    for c in capped:
        ids = fetch_ids({'sexId': c['sex'], 'nationality': c['nat'], 'arrestWarrantCountryId': c['aw']})
        miss = [i for i in ids if i not in db_ids]
        if miss:
            print(f"  EKSIK {len(miss)}: sex={c['sex']} nat={c['nat']} aw={c['aw']} -> {miss[:5]}")
            missing_total.extend(miss)
    print(f"Toplam DB-disi: {len(set(missing_total))}")

# == 2. sex=U cap olmayan kombinasyonlar ==
print("\n=== sex=U detay ===")
for nat in ALL_HIGH:
    t = total({'sexId': 'U', 'nationality': nat})
    db_u = conn.execute("SELECT COUNT(1) FROM notices WHERE (nationality=? OR all_nationalities LIKE ?) AND sex='U'",
                        (nat, f'%{nat}%')).fetchone()[0]
    status = "  OK" if t == db_u else f"  FARK api={t} db={db_u}"
    print(f"  nat={nat} sex=U:{status}")
    time.sleep(0.15)

# == 3. ALL nats × 5 rastgele AW ornekleme: DB'de olmayan kayit var mi? ==
print("\n=== ALL nat × 5 rastgele AW spot check ({} sorgu) ===".format(len(NATS)*5))
found_missing = {}
random.seed(42)
for nat in NATS:
    for aw in random.sample(NATS, 5):
        ids = fetch_ids({'nationality': nat, 'arrestWarrantCountryId': aw})
        for eid in ids:
            if eid not in db_ids:
                found_missing[eid] = (nat, aw)
        time.sleep(0.08)

print(f"\nOrneklemede DB-disi kayit: {len(found_missing)}")
for eid, (nat, aw) in list(found_missing.items())[:20]:
    print(f"  {eid}  nat={nat} aw={aw}")

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

def total(params):
    r = client._session.get(url, params={**params, 'resultPerPage': 1, 'page': 1}, headers=h, timeout=15)
    if r.status_code == 200:
        return r.json().get('total', 0)
    return f'HTTP_{r.status_code}'

conn = sqlite3.connect('/data/notices.db')
db_ids = set(r[0] for r in conn.execute('SELECT entity_id FROM notices').fetchall())
db_total = len(db_ids)
print(f"DB total: {db_total}")

# API total stabil mi?
print("\n=== API total stability ===")
for i in range(3):
    t = total({})
    print(f"  query {i+1}: {t}")
    time.sleep(1.0)

# Medium-count nat'lari bul
medium_nats = [r[0] for r in conn.execute(
    "SELECT nationality, COUNT(1) as cnt FROM notices "
    "WHERE nationality IS NOT NULL "
    "GROUP BY nationality HAVING cnt BETWEEN 50 AND 160 ORDER BY cnt DESC"
).fetchall()]
print(f"\nMedium-count nats (50-160 in DB): {medium_nats}")

# 160 cap kontrolu
print("\n=== Medium-nat 160 cap check ===")
capped = []
for nat in medium_nats:
    for sex in ['M', 'F']:
        t = total({'sexId': sex, 'nationality': nat})
        if isinstance(t, int) and t > 160:
            capped.append((sex, nat, t))
            print(f"  CAP! sex={sex} nat={nat}: {t}")
        time.sleep(0.2)
if not capped:
    print("  Hicbir medium-nat 160 capini asmiyor -> bu grup sorun degil")

# ASIL TEST: medium-nat x ALL AW - hic yapilmadi!
# Mevcut passler: highNat(6) x ALL AW ve ALL nat x highAW(6)
# Atlanilan: mediumNat x mediumAW kombinasyonlari
NATS = _ic.InterpolClient.ALL_NATIONALITIES
HIGH = ['RU', 'SV', 'IN', 'AR', 'PK', 'GT']
# Bu natlarin AW kombinasyonu yapildı mı?
# Pass 12-15: highNat × ALL AW ve ALL nat × highAW
# Atlanilan: mediumNat × mediumAW (her ikisi de high listesinde degil)
print("\n=== mediumNat x mediumAW spot check ===")
sample_nats = [n for n in medium_nats if n not in HIGH][:6]
sample_aws  = [n for n in NATS if n not in HIGH][:20]
found_new = {}
for nat in sample_nats:
    for aw in sample_aws:
        p = {'nationality': nat, 'arrestWarrantCountryId': aw, 'resultPerPage': 160}
        r = client._session.get(url, params=p, headers=h, timeout=15)
        if r.status_code == 200:
            items = r.json().get('_embedded', {}).get('notices', [])
            for n in items:
                eid = n.get('entity_id', '')
                if eid and eid not in db_ids:
                    found_new[eid] = {'nat': nat, 'aw': aw,
                                      'name': n.get('name'), 'forename': n.get('forename'),
                                      'nats': n.get('nationalities')}
        time.sleep(0.25)

print(f"Bu kombinasyonlarda DB'de olmayan kayit: {len(found_new)}")
for eid, info in list(found_new.items())[:15]:
    print(f"  {eid}  {info['name']} {info['forename']}  nat={info['nat']} aw={info['aw']} nats={info['nats']}")
