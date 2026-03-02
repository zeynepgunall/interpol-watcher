"""
Hangi nationality+sexId kombinasyonlari hala 160 cap'i asiyor?
Bu kombinasyonlar icin 1yr age drilling lazim.
"""
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

NATS = client.ALL_NATIONALITIES

capped = []
print('Checking M+nat and F+nat totals...')
for nat in NATS:
    for sex in ['M', 'F']:
        r = client._session.get(url,
            params={'resultPerPage': 1, 'page': 1, 'sexId': sex, 'nationality': nat},
            headers=h, timeout=15)
        if r.status_code == 200:
            total = r.json().get('total', 0)
            if total > 160:
                capped.append((sex, nat, total))
                print(f'  CAP sexId={sex} nat={nat}: {total}')
        elif r.status_code == 403:
            print(f'403 at {sex}+{nat}, stopping')
            break
        time.sleep(0.15)

print()
print('=== sex+nat combos exceeding 160 ===')
for sex, nat, total in sorted(capped, key=lambda x: -x[2]):
    print(f'  sexId={sex} nationality={nat}: total={total}')

# Also check age 0-9
print()
for sex in ['M', 'F']:
    r = client._session.get(url,
        params={'resultPerPage': 1, 'page': 1, 'sexId': sex, 'ageMin': 0, 'ageMax': 9},
        headers=h, timeout=15)
    if r.status_code == 200:
        print(f'sexId={sex} age 0-9: total={r.json().get("total",0)}')
    time.sleep(0.3)
