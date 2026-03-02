import sys, time
sys.path.insert(0, '/app')
from fetcher.interpol_client import InterpolClient

client = InterpolClient('https://ws-public.interpol.int')
client._warmup_session()
url = 'https://ws-public.interpol.int/notices/v1/red'
h = client._build_headers(accept_json=True)
h['Referer'] = 'https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices'
h['Sec-Fetch-Site'] = 'same-site'
h['Sec-Fetch-Mode'] = 'cors'

# TR total ve breakdown
for params in [
    {'nationality': 'TR'},
    {'nationality': 'TR', 'sexId': 'M'},
    {'nationality': 'TR', 'sexId': 'F'},
    {'nationality': 'TR', 'sexId': 'U'},
    {'arrestWarrantCountryId': 'TR'},
]:
    r = client._session.get(url, params={**params, 'resultPerPage': 1}, headers=h, timeout=15)
    if r.status_code == 200:
        print(f"params={params}  total={r.json().get('total', 0)}")
    else:
        print(f"params={params}  status={r.status_code}")
    time.sleep(0.4)

# TR sayfalarini cek - tum entity_id'leri al
print()
seen = {}
for sex in ['M', 'F', 'U', None]:
    p = {'nationality': 'TR', 'resultPerPage': 160, 'page': 1}
    if sex:
        p['sexId'] = sex
    r = client._session.get(url, params=p, headers=h, timeout=15)
    if r.status_code == 200:
        items = r.json().get('_embedded', {}).get('notices', [])
        for n in items:
            eid = n.get('entity_id', '')
            if eid and eid not in seen:
                seen[eid] = {'name': n.get('name'), 'forename': n.get('forename'), 'sex': sex}
    time.sleep(0.5)

print(f"API'den cekilen TR unique: {len(seen)}")

# DB ile karsilastir
import sqlite3
conn = sqlite3.connect('/data/notices.db')
db_ids = {r[0] for r in conn.execute("SELECT entity_id FROM notices WHERE nationality='TR'").fetchall()}
print(f"DB'deki TR: {len(db_ids)}")
print()

missing = {k: v for k, v in seen.items() if k not in db_ids}
print(f"DB'de EKSIK olan TR kayitlari ({len(missing)}):")
for eid, info in missing.items():
    print(f"  {eid}  {info['name']} {info['forename']}  sex={info['sex']}")
