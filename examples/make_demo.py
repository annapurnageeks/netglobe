"""Build the static demo (docs/index.html) for GitHub Pages, which can't run Python or read your connections.

The demo uses a hand-made, realistic sample of what a browser-heavy afternoon looks like — not anyone's real
machine. Edit SAMPLE below to change it. The globe, the panel and the tracker flags all work from this data.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import netglobe as n

HOME = {"country": "DE", "name": "Germany", "lat": 51.0, "lon": 9.0}

# (app, org, country-code, is_tracker, tracker_name)
SAMPLE = [
    ("Chrome", "Google", "US", False, None),
    ("Chrome", "Google Analytics", "US", True, "Google Analytics"),
    ("Chrome", "Google Ads (DoubleClick)", "US", True, "Google Ads (DoubleClick)"),
    ("Chrome", "Meta tracking", "IE", True, "Meta tracking"),
    ("Chrome", "Criteo", "FR", True, "Criteo"),
    ("Chrome", "The Trade Desk", "US", True, "The Trade Desk"),
    ("Chrome", "Cloudflare", "US", False, None),
    ("Chrome", "Amazon CloudFront", "US", False, None),
    ("Chrome", "Akamai", "NL", False, None),
    ("Chrome", "Hotjar (session replay)", "US", True, "Hotjar (session replay)"),
    ("Slack", "Amazon AWS", "US", False, None),
    ("Slack", "Segment", "US", True, "Segment"),
    ("Spotify", "Google", "US", False, None),
    ("Spotify", "Spotify", "SE", False, None),
    ("Spotify", "Amplitude", "US", True, "Amplitude"),
    ("Mail", "Apple iCloud", "US", False, None),
    ("Mail", "Microsoft", "IE", False, None),
    ("Dropbox", "Amazon AWS", "US", False, None),
    ("Dropbox", "Mixpanel", "US", True, "Mixpanel"),
    ("TikTok", "TikTok / ByteDance", "SG", False, None),
    ("TikTok", "AppsFlyer (attribution)", "IL", True, "AppsFlyer (attribution)"),
    ("Code", "GitHub", "US", False, None),
    ("Code", "Sentry (error tracking)", "US", True, "Sentry (error tracking)"),
    ("Weather", "Amazon AWS", "DE", False, None),
    ("Weather", "Adjust (attribution)", "DE", True, "Adjust (attribution)"),
]


def build():
    countries = n.load_json("countries.json")
    flows = []
    for app, org, cc, tracker, tname in SAMPLE:
        info = countries.get(cc, ["Unknown", None, None])
        flows.append({"app": app, "ip": "", "port": 443, "host": "", "org": org, "tracker": tracker,
                      "tracker_name": tname, "country": cc, "place": info[0], "lat": info[1], "lon": info[2], "count": 1})
    apps = {f["app"] for f in flows}
    data = {"home": HOME, "at": "sample", "flows": flows,
            "summary": {"connections": len(flows), "apps": len(apps),
                        "countries": len({f["country"] for f in flows}),
                        "trackers": sum(f["tracker"] for f in flows)}}
    config = {"version": n.VERSION, "home": HOME, "landmask": n.load_json("landmask.json"), "demo": data}
    page = (ROOT / "globe.html").read_text(encoding="utf-8")
    page = page.replace("/*__CONFIG__*/null", json.dumps(config).replace("</", "<\\/"))
    out = ROOT / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({data['summary']['connections']} connections, {data['summary']['trackers']} trackers)")


if __name__ == "__main__":
    build()
