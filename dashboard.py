"""Server-rendered, dependency-free status board. All stored text is escaped."""
from html import escape

STYLE = '''
*{box-sizing:border-box}body{margin:0;background:#f6f6f6;color:#171717;font:16px/1.6 Arial,Helvetica,sans-serif}main{max-width:1040px;margin:auto;padding:48px 24px}header{display:flex;justify-content:space-between;gap:24px;align-items:center;border-bottom:2px solid #171717;padding-bottom:24px}h1{font-size:32px;letter-spacing:-1px;margin:0}h2{font-size:22px;margin:0 0 16px}p{margin:8px 0}.eyebrow,small{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#555}.banner{padding:28px;background:#171717;color:white;margin:32px 0}.banner p{color:#ddd}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:40px}.metric{border:1px solid #ccc;padding:20px;background:white}.metric strong{display:block;font-size:30px}.incident{background:white;border:1px solid #ccc;padding:24px;margin:16px 0}.incident h3{margin:8px 0;font-size:20px}.badge{display:inline-block;border:1px solid #555;padding:2px 8px;font-size:12px;text-transform:uppercase;letter-spacing:.04em}.timeline{border-left:2px solid #ccc;padding-left:24px;margin:24px 0 0 8px;list-style:none}.timeline li{padding:0 0 20px}.timeline p{white-space:pre-wrap;overflow-wrap:anywhere}time{font-size:13px;color:#555}a{color:inherit;text-underline-offset:4px}footer{border-top:1px solid #ccc;margin-top:40px;padding-top:20px;color:#555;font-size:13px}.empty{border:1px dashed #aaa;padding:24px}.incident h3,.incident small{overflow-wrap:anywhere}@media(max-width:600px){main{padding:24px 16px}header{display:block}.grid{gap:8px}.metric{padding:12px}.metric strong{font-size:24px}h1{font-size:28px}}
'''


def render(store):
    with store.snapshot():
        return _render(store)


def _render(store):
    snapshot = store.status()
    incidents = snapshot['incidents']
    active = [i for i in incidents if i['state'] != 'resolved']
    resolved = [i for i in incidents if i['state'] == 'resolved']
    sections = []
    for title, items in [('Active incidents', active), ('Resolved incidents', resolved)]:
        cards = []
        for item in items:
            events = store.get(item['id'])['events']
            timeline = ''.join(
                '<li><span class="badge">' + escape(e['state']) + '</span> '
                '<time datetime="' + escape(e['at'], quote=True) + '">' + escape(e['at'][:19].replace('T', ' ')) + ' UTC</time>'
                '<p>' + escape(e['message']) + '</p></li>' for e in reversed(events))
            cards.append('<article class="incident"><small>' + escape(item['service']) + '</small><h3>' + escape(item['title']) + '</h3><span class="badge">' + escape(item['state']) + '</span><ol class="timeline">' + timeline + '</ol></article>')
        sections.append('<section aria-label="' + title + '"><h2>' + title + '</h2>' + (''.join(cards) or '<p class="empty">No ' + title.lower() + '.</p>') + '</section>')
    headline = 'Service disruption reported' if active else 'All reported incidents resolved' if incidents else 'No incidents reported'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Status Ledger | Service status</title><style>' + STYLE + '</style></head><body><main>'
            '<header><div><div class="eyebrow">Synthetic hosting environment</div><h1>Status Ledger</h1></div><a href="/api/status">View JSON status</a></header>'
            '<div class="banner" role="status"><h2>' + headline + '</h2><p>Manually recorded updates. This board does not measure uptime or monitor live services.</p></div>'
            '<div class="grid"><div class="metric"><small>Active</small><strong>' + str(len(active)) + '</strong></div><div class="metric"><small>Resolved</small><strong>' + str(len(resolved)) + '</strong></div><div class="metric"><small>Total</small><strong>' + str(len(incidents)) + '</strong></div></div>' + ''.join(sections) +
            '<footer>Demo data only · Times shown in UTC · Reload to fetch the latest updates</footer></main></body></html>')
