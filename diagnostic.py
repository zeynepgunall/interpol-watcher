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

# Unfiltered: tum sayfalari tara, unique entity_id topla
all_ids = {}  # entity_id -> first seen page
for pg in range(1, 60):
    r = client._session.get(url, params={'resultPerPage': 160, 'page': pg}, headers=h, timeout=20)
    if r.status_code != 200:
        print('STOP page=%d status=%d' % (pg, r.status_code))
        break
    d = r.json()
    items = d.get('_embedded', {}).get('notices', [])
    links = list(d.get('_links', {}).keys())
    new = 0
    for n in items:
        eid = n.get('entity_id', '')
        if eid not in all_ids:
            all_ids[eid] = pg
            new += 1
    print('page=%d items=%d new=%d total_unique=%d links=%s' % (
        pg, len(items), new, len(all_ids), links))
    if 'next' not in d.get('_links', {}):
        print('--- pagination end ---')
        break
    time.sleep(0.4)

print()
print('UNFILTERED_UNIQUE:', len(all_ids))
print('UNFILTERED_API_TOTAL:', d.get('total'))

# per-page new contribution
page_contributions = {}
for eid, pg in all_ids.items():
    page_contributions[pg] = page_contributions.get(pg, 0) + 1
print('New contributions per page:')
for pg in sorted(page_contributions):
    print('  page %d: %d new' % (pg, page_contributions[pg]))

# Multi-nat check - sample 500 entries from page 1-4
multi_nat = []
for pg in range(1, 4):
    r2 = client._session.get(url, params={'resultPerPage': 160, 'page': pg, 'nationality': 'RU'},
                             headers=h, timeout=20)
    for n in r2.json().get('_embedded', {}).get('notices', []):
        nats = n.get('nationalities') or []
        if len(nats) > 1:
            multi_nat.append((n.get('entity_id'), nats))
    time.sleep(0.3)

print()
print('Multi-nationality in first 3 RU pages: %d' % len(multi_nat))
for eid, nats in multi_nat[:5]:
    print('  %s -> %s' % (eid, nats))
