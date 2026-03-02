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

# sexId tek basina 5545 (M) ve 909 (F) - ama bunlara erisemedik cunku 160 cap var
# Check: M+nationality ile ne kadar covered?
import re
overflowing = []

for nat in client.ALL_NATIONALITIES:
    r = client._session.get(url, params=dict(resultPerPage=1, page=1, sexId='M', nationality=nat), headers=h, timeout=20)
    total = r.json().get('total', 0)
    if total > 160:
        last = r.json().get('_links', {}).get('last', {}).get('href', '')
        lp = re.search(r'page=(\d+)', last)
        pages = lp.group(1) if lp else '?'
        overflowing.append((nat, total, pages))
        print(f'M+nationality={nat}: total={total} pages={pages}  <-- OVERFLOW')

print()
print('Overflowing nationality+M combos:', overflowing)
