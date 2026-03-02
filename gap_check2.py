import sys, time, sqlite3
sys.path.insert(0, '/tmp')
import interpol_client as _ic
client = _ic.InterpolClient('https://ws-public.interpol.int')
client._warmup_session()
url = 'https://ws-public.interpol.int/notices/v1/red'
h = client._build_headers(accept_json=True)
h['Referer'] = 'https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices'
h['Sec-Fetch-Site'] = 'same-site'
h['Sec-Fetch-Mode'] = 'cors'

conn = sqlite3.connect('/data/notices.db')
db_ids = set(r[0] for r in conn.execute('SELECT entity_id FROM notices').fetchall())
print(f"DB: {len(db_ids)}")

def fetch_all_ids(params):
    ids, page = [], 1
    while True:
        r = client._session.get(url, params={**params,'resultPerPage':160,'page':page}, headers=h, timeout=20)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}")
            break
        d = r.json()
        items = d.get('_embedded',{}).get('notices',[])
        ids.extend(n['entity_id'] for n in items if 'entity_id' in n)
        if len(items) < 160: break
        page += 1
        time.sleep(0.5)
    return ids

# 5 capped combo: IN/IN, AR/AR, F/RU/RU, M/RU/RU, M/SV/SV
# (RU ve SV icin 1yr passler var, gercekten kapatildi mi?)
checks = [
    {'sexId': 'M', 'nationality': 'IN', 'arrestWarrantCountryId': 'IN'},
    {'sexId': 'M', 'nationality': 'AR', 'arrestWarrantCountryId': 'AR'},
    {'sexId': 'F', 'nationality': 'RU', 'arrestWarrantCountryId': 'RU'},
    {'sexId': 'M', 'nationality': 'RU', 'arrestWarrantCountryId': 'RU'},
    {'sexId': 'M', 'nationality': 'SV', 'arrestWarrantCountryId': 'SV'},
]
all_missing = []
for p in checks:
    ids = fetch_all_ids(p)
    missing = [i for i in ids if i not in db_ids]
    all_missing.extend(missing)
    tag = p.get('nationality','')
    print(f"sex={p.get('sexId')} nat={tag} aw={p.get('arrestWarrantCountryId','')}: api={len(ids)} missing={len(missing)} {missing[:3]}")
    time.sleep(0.5)

print(f"\nToplam unique eksik: {len(set(all_missing))}")

# Eksik kayitlarin detaylari
if all_missing:
    for eid in list(set(all_missing))[:10]:
        eid_api = eid.replace('/', '-')
        r = client._session.get(f"https://ws-public.interpol.int/notices/v1/red/{eid_api}", headers=h, timeout=15)
        if r.status_code == 200:
            d = r.json()
            print(f"  {eid}  {d.get('name')} {d.get('forename')}  nats={d.get('nationalities')}  dob={d.get('date_of_birth')}")
        time.sleep(0.3)
