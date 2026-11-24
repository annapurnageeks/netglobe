#!/usr/bin/env python3
"""
netglobe: watch where your Mac sends your data, live, on a spinning globe.

    python3 netglobe.py                 # open the globe in your browser
    python3 netglobe.py --home US       # put "you" in a different country (default: your system region)
    python3 netglobe.py --json          # print the current connections as JSON and exit
    python3 netglobe.py --once          # one text snapshot in the terminal, then exit

Every few seconds netglobe lists the network connections your apps have open (with `lsof`, no admin needed),
finds who is on the other end and roughly where they are, and draws an arc from you to them. It flags the
connections that are tracking you, and the ones going somewhere surprising.

It only reads. It changes nothing, blocks nothing, and makes no network requests of its own: the country lookup
is a table bundled with the tool, so the addresses you talk to never leave your machine. Only the Python
standard library is used.
"""

import argparse
import base64
import gzip
import ipaddress
import json
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "0.1.0"
PROJECT_URL = "https://github.com/annapurnageeks/netglobe"
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# Hostname fragments that identify an organization behind an address. Checked against reverse DNS.
ORG_BY_HOST = [
    ("1e100.net", "Google"), ("google", "Google"), ("googleusercontent", "Google"), ("gvt1.com", "Google"),
    ("youtube", "YouTube"), ("ytimg", "YouTube"),
    ("amazonaws.com", "Amazon AWS"), ("aws", "Amazon AWS"), ("cloudfront", "Amazon CloudFront"), ("amazon", "Amazon"),
    ("azure", "Microsoft Azure"), ("microsoft", "Microsoft"), ("windows.net", "Microsoft"), ("office", "Microsoft"),
    ("apple.com", "Apple"), ("icloud", "Apple iCloud"), ("mzstatic", "Apple"), ("aaplimg", "Apple"), ("cdn-apple", "Apple"),
    ("fbcdn", "Meta / Facebook"), ("facebook", "Meta / Facebook"), ("instagram", "Instagram"), ("whatsapp", "WhatsApp"),
    ("cloudflare", "Cloudflare"), ("akamai", "Akamai"), ("fastly", "Fastly"), ("edgekey", "Akamai"), ("edgesuite", "Akamai"),
    ("github", "GitHub"), ("githubusercontent", "GitHub"), ("gitlab", "GitLab"),
    ("anthropic", "Anthropic"), ("openai", "OpenAI"), ("ngrok", "ngrok"), ("digitalocean", "DigitalOcean"),
    ("hetzner", "Hetzner"), ("ovh", "OVH"), ("linode", "Linode"), ("vultr", "Vultr"),
    ("netflix", "Netflix"), ("nflxvideo", "Netflix"), ("spotify", "Spotify"), ("slack", "Slack"), ("zoom", "Zoom"),
    ("tiktok", "TikTok"), ("bytedance", "TikTok / ByteDance"), ("twitter", "X / Twitter"), ("twimg", "X / Twitter"),
    ("x.com", "X / Twitter"), ("reddit", "Reddit"), ("discord", "Discord"), ("telegram", "Telegram"),
]

# Known trackers and ad networks. A connection to one of these is someone profiling you. (fragment, name)
TRACKERS = [
    ("doubleclick", "Google Ads (DoubleClick)"), ("google-analytics", "Google Analytics"),
    ("googletagmanager", "Google Tag Manager"), ("googlesyndication", "Google AdSense"), ("googleadservices", "Google Ads"),
    ("google-analytics", "Google Analytics"), ("app-measurement", "Google/Firebase Analytics"),
    ("scorecardresearch", "Comscore"), ("quantserve", "Quantcast"), ("criteo", "Criteo"),
    ("adnxs", "AppNexus (ad exchange)"), ("rubiconproject", "Magnite (ad exchange)"), ("pubmatic", "PubMatic ads"),
    ("taboola", "Taboola"), ("outbrain", "Outbrain"), ("adsrvr.org", "The Trade Desk"), ("amazon-adsystem", "Amazon Ads"),
    ("branch.io", "Branch (attribution)"), ("adjust.com", "Adjust (attribution)"), ("appsflyer", "AppsFlyer (attribution)"),
    ("segment.io", "Segment"), ("segment.com", "Segment"), ("mixpanel", "Mixpanel"), ("amplitude", "Amplitude"),
    ("sentry", "Sentry (error tracking)"), ("bugsnag", "Bugsnag"), ("fullstory", "FullStory (session replay)"),
    ("hotjar", "Hotjar (session replay)"), ("facebook", "Meta tracking"), ("fbcdn", "Meta tracking"),
    ("crashlytics", "Firebase Crashlytics"), ("flurry", "Flurry analytics"), ("chartbeat", "Chartbeat"),
    ("newrelic", "New Relic"), ("doubleverify", "DoubleVerify"), ("moatads", "Oracle Moat ads"),
]

# Big networks whose addresses often lack reverse DNS. (CIDR prefix as int tuple, org). Loaded lazily.
KNOWN_RANGES = [
    ("13.107.0.0/16", "Microsoft"), ("20.0.0.0/8", "Microsoft Azure"), ("40.74.0.0/15", "Microsoft Azure"),
    ("52.0.0.0/8", "Amazon AWS"), ("54.0.0.0/8", "Amazon AWS"), ("3.0.0.0/8", "Amazon AWS"), ("18.0.0.0/8", "Amazon AWS"),
    ("104.16.0.0/12", "Cloudflare"), ("172.64.0.0/13", "Cloudflare"), ("173.245.48.0/20", "Cloudflare"),
    ("8.8.8.0/24", "Google"), ("142.250.0.0/15", "Google"), ("172.217.0.0/16", "Google"), ("216.58.192.0/19", "Google"),
    ("140.82.112.0/20", "GitHub"), ("185.199.108.0/22", "GitHub"),
    ("157.240.0.0/16", "Meta / Facebook"), ("31.13.24.0/21", "Meta / Facebook"),
    ("17.0.0.0/8", "Apple"), ("23.192.0.0/11", "Akamai"), ("151.101.0.0/16", "Fastly"),
]


def load_json(name):
    return json.loads((DATA / name).read_text())


class Geo:
    """Offline IP -> country -> point on the globe, from tables bundled with the tool."""

    def __init__(self):
        self.countries = load_json("countries.json")           # alpha2 -> [name, lat, lon]
        table = load_json("ip2country.json")
        self.cc = table["cc"]
        self.starts = struct.unpack(f">{table['n']}I", gzip.decompress(base64.b64decode(table["starts"])))
        self.ends = struct.unpack(f">{table['n']}I", gzip.decompress(base64.b64decode(table["ends"])))
        self.idx = struct.unpack(f">{table['n']}H", gzip.decompress(base64.b64decode(table["idx"])))
        self.ranges = [(ipaddress.ip_network(cidr), org) for cidr, org in KNOWN_RANGES]
        v6 = load_json("ip2country6.json")
        self.cc6 = v6["cc"]
        self.starts6 = struct.unpack(f">{v6['n']}Q", gzip.decompress(base64.b64decode(v6["starts"])))
        self.plen6 = gzip.decompress(base64.b64decode(v6["plen"]))
        self.idx6 = struct.unpack(f">{v6['n']}H", gzip.decompress(base64.b64decode(v6["idx"])))

    def country(self, ip_int):
        import bisect
        i = bisect.bisect_right(self.starts, ip_int) - 1
        if 0 <= i < len(self.starts) and self.starts[i] <= ip_int < self.ends[i]:
            return self.cc[self.idx[i]]
        return None

    def country6(self, ip_int):
        import bisect
        top = ip_int >> 64                                    # allocations are identified by the top 64 bits
        i = bisect.bisect_right(self.starts6, top) - 1
        if 0 <= i < len(self.starts6):
            span = 1 << max(0, 64 - self.plen6[i])
            if self.starts6[i] <= top < self.starts6[i] + span:
                return self.cc6[self.idx6[i]]
        return None

    def locate(self, ip):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        cc = self.country6(int(addr)) if addr.version == 6 else self.country(int(addr))
        info = self.countries.get(cc) if cc else None
        if not info:
            return {"country": cc, "name": cc or "Unknown", "lat": None, "lon": None}
        return {"country": cc, "name": info[0], "lat": info[1], "lon": info[2]}

    def known_org(self, ip):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        for net, org in self.ranges:
            if addr in net:
                return org
        return None


# ---------------------------------------------------------------------------------------------
# Watching the connections
# ---------------------------------------------------------------------------------------------

def tidy_app(name):
    """lsof truncates app names and escapes spaces as \\x20."""
    return name.replace("\\x20", " ").strip()


def snapshot(run=None):
    """Every established outbound TCP connection: (app, pid, remote_ip, remote_port)."""
    run = run or (lambda: subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:ESTABLISHED"], capture_output=True, text=True, timeout=15).stdout)
    out = run()
    flows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9:
            continue
        app, pid, name = tidy_app(parts[0]), parts[1], parts[-2] if parts[-1].startswith("(") else parts[-1]
        match = re.search(r"->(\[?[0-9a-fA-F:.]+\]?):(\d+)", name)
        if not match:
            continue
        ip = match.group(1).strip("[]")
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
            continue
        flows.append({"app": app, "pid": pid, "ip": ip, "port": int(match.group(2))})
    return flows


class Watcher:
    """Turns raw connections into located, named flows, caching the slow parts (reverse DNS)."""

    def __init__(self, geo):
        self.geo = geo
        self.hosts = {}       # ip -> hostname ("" if none)
        self.lock = threading.Lock()

    def hostname(self, ip):
        with self.lock:
            if ip in self.hosts:
                return self.hosts[ip]
        name = ""
        try:
            socket.setdefaulttimeout(1.0)
            name = socket.gethostbyaddr(ip)[0]
        except (OSError, socket.herror):
            name = ""
        with self.lock:
            self.hosts[ip] = name
        return name

    def classify(self, ip, host):
        """(organization, is_tracker, tracker_name)."""
        h = host.lower()
        for fragment, name in TRACKERS:
            if fragment in h:
                return name, True, name
        for fragment, org in ORG_BY_HOST:
            if fragment in h:
                return org, False, None
        org = self.geo.known_org(ip)
        if org:
            return org, False, None
        if host:                                   # fall back to the registered domain
            labels = host.split(".")
            return (".".join(labels[-2:]) if len(labels) >= 2 else host), False, None
        return "Unknown", False, None

    def enrich(self, flows):
        out = {}
        for f in flows:
            host = self.hostname(f["ip"])
            org, is_tracker, tracker = self.classify(f["ip"], host)
            place = self.geo.locate(f["ip"]) or {"name": "Unknown", "lat": None, "lon": None, "country": None}
            key = (f["app"], org, f["ip"])
            if key in out:
                out[key]["count"] += 1
                continue
            out[key] = {"app": f["app"], "ip": f["ip"], "port": f["port"], "host": host, "org": org,
                        "tracker": is_tracker, "tracker_name": tracker, "country": place["country"],
                        "place": place["name"], "lat": place["lat"], "lon": place["lon"], "count": 1}
        return list(out.values())


# ---------------------------------------------------------------------------------------------
# Home location (where "you" are on the globe), found offline
# ---------------------------------------------------------------------------------------------

def home_country(override=None):
    if override:
        return override.upper()
    try:
        locale = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=5).stdout
        match = re.search(r"_([A-Z]{2})", locale)
        if match:
            return match.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "US"


def home_point(geo, override=None):
    cc = home_country(override)
    info = geo.countries.get(cc) or geo.countries.get("US")
    return {"country": cc, "name": info[0], "lat": info[1], "lon": info[2]}


# ---------------------------------------------------------------------------------------------
# One report
# ---------------------------------------------------------------------------------------------

def report(geo, watcher, home, snap=None):
    flows = watcher.enrich((snap or snapshot)())
    trackers = [f for f in flows if f["tracker"]]
    by_app = {}
    for f in flows:
        by_app.setdefault(f["app"], []).append(f)
    countries = {f["country"] for f in flows if f["country"]}
    return {"tool": "netglobe", "version": VERSION, "at": time.strftime("%H:%M:%S"),
            "home": home, "flows": flows,
            "summary": {"connections": len(flows), "apps": len(by_app), "countries": len(countries),
                        "trackers": len(trackers)}}


def print_report(data, color):
    paint = (lambda c, t: f"\033[{c}m{t}\033[0m") if color else (lambda c, t: t)
    s = data["summary"]
    print()
    print(paint("1;46;30", f"  netglobe  ") + f"  {data['at']}  from {data['home']['name']}")
    print(f"{s['connections']} connections · {s['apps']} apps · {s['countries']} countries · "
          + paint("1;31" if s["trackers"] else "2", f"{s['trackers']} trackers"))
    by_app = {}
    for f in data["flows"]:
        by_app.setdefault(f["app"], []).append(f)
    for app, flows in sorted(by_app.items(), key=lambda kv: -len(kv[1])):
        print("\n" + paint("1", app) + paint("2", f"  ({len(flows)} connection{'s' if len(flows) > 1 else ''})"))
        seen = set()
        for f in sorted(flows, key=lambda f: (not f["tracker"], f["org"])):
            tag = (f["org"], f["place"])
            if tag in seen:
                continue
            seen.add(tag)
            mark = paint("1;31", "⚑ tracker") if f["tracker"] else paint("2", "·")
            where = f["place"] + (f" ({f['country']})" if f["country"] else "")
            print(f"  {mark} {paint('1', f['org']):<34} {paint('2', where)}")
            if f["tracker"]:
                print(paint("2", f"           {f['tracker_name']}"))
    print()


# ---------------------------------------------------------------------------------------------
# The live server
# ---------------------------------------------------------------------------------------------

def make_handler(geo, watcher, home):
    page = (HERE / "globe.html").read_text(encoding="utf-8")
    config = json.dumps({"version": VERSION, "home": home, "landmask": load_json("landmask.json")})
    page = page.replace("/*__CONFIG__*/null", config.replace("</", "<\\/"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, kind="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send(200, page, "text/html; charset=utf-8")
            elif self.path.startswith("/api/connections"):
                try:
                    self.send(200, json.dumps(report(geo, watcher, home)))
                except Exception as error:
                    self.send(500, json.dumps({"error": f"{type(error).__name__}: {error}"}))
            else:
                self.send(404, json.dumps({"error": "not found"}))

    return Handler


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Watch where your Mac sends your data, live, on a globe.")
    parser.add_argument("--home", help="your country code (default: your system region)")
    parser.add_argument("--json", action="store_true", help="print the current connections as JSON and exit")
    parser.add_argument("--once", action="store_true", help="print one text snapshot and exit")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="don't open the browser")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    if sys.platform != "darwin":
        sys.exit("netglobe watches macOS for now. Linux support is on the roadmap: " + PROJECT_URL)
    if not (DATA / "ip2country.json").exists():
        sys.exit("netglobe's data files are missing. Clone the whole repository, including the data/ folder.")

    geo = Geo()
    watcher = Watcher(geo)
    home = home_point(geo, args.home)

    if args.json:
        print(json.dumps(report(geo, watcher, home), indent=2))
        return
    if args.once:
        print_report(report(geo, watcher, home), sys.stdout.isatty() and not args.no_color)
        return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(geo, watcher, home))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"netglobe is live at {url}   (you are in {home['name']})")
    print("Press Ctrl-C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
