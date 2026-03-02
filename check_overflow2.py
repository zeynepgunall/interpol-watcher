import sys
sys.path.insert(0, '/app')
from fetcher.interpol_client import InterpolClient

client = InterpolClient('https://ws-public.interpol.int')
client._warmup_session()

url = 'https://ws-public.interpol.int/notices/v1/red'
h = client._build_headers(accept_json=True)
h['Referer'] = 'https://www.interpol.int/How-we-work/Notices/Red-Notices/View-Red-Notices'
h['Sec-Fetch-Site'] = 'same-site'
h['Sec-Fetch-Mode'] = 'cors'

# Check all nationality (M+F combined) totals to find ones over 160
overflowing = []
for nat in client.ALL_NATIONALITIES:
    r = client._session.get(url, params=dict(resultPerPage=1, page=1, nationality=nat), headers=h, timeout=20)
    total = r.json().get('total', 0)
    if total > 160:
        overflowing.append((nat, total))

print("Overflowing (>160) nationality combos:")
for nat, total in sorted(overflowing, key=lambda x: -x[1]):
    print(f"  nationality={nat}: {total}")

print()

# Also check arrest warrant country
overflowing2 = []
for country in client.ALL_NATIONALITIES:
    r = client._session.get(url, params=dict(resultPerPage=1, page=1, arrestWarrantCountryId=country), headers=h, timeout=20)
    total = r.json().get('total', 0)
    if total > 160:
        overflowing2.append((country, total))

print("Overflowing (>160) arrestWarrantCountryId combos:")
for c, total in sorted(overflowing2, key=lambda x: -x[1]):
    print(f"  arrestWarrantCountryId={c}: {total}")
