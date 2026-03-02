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

tests = [
    {'sexId': 'M'},
    {'sexId': 'F'},
    {'ageMin': 1, 'ageMax': 100},
    {'sexId': 'M', 'nationality': 'US'},
    {'sexId': 'F', 'nationality': 'US'},
    {'sexId': 'M', 'arrestWarrantCountryId': 'US'},
    {'sexId': 'F', 'arrestWarrantCountryId': 'US'},
]
for p in tests:
    r = client._session.get(url, params=dict(resultPerPage=160, page=1, **p), headers=h, timeout=20)
    d = r.json()
    last = d.get('_links', {}).get('last', {}).get('href', '')
    import re
    last_page = re.search(r'page=(\d+)', last)
    lp = last_page.group(1) if last_page else '1'
    print(str(p) + ' -> total=' + str(d.get('total')) + ' last_page=' + lp)
