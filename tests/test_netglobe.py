"""Tests for netglobe. Run with:  python3 -m unittest discover tests

These test the deterministic engine — parsing lsof, offline geolocation, org and tracker classification — with
canned command output, so they need no live network and no admin.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import netglobe as n  # noqa: E402

# A fake `lsof -nP -iTCP -sTCP:ESTABLISHED`, covering the shapes the real one produces.
LSOF = """COMMAND     PID           USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Google\\x20  1388 sam   45u  IPv4 0x1 0t0  TCP 192.168.1.4:61315->104.18.39.21:443 (ESTABLISHED)
Google\\x20  1388 sam   60u  IPv4 0x2 0t0  TCP 192.168.1.4:49852->140.82.112.26:443 (ESTABLISHED)
Spotify     900  sam   12u  IPv6 0x3 0t0  TCP [2600:1f18::1]:50001->[2a03:2880:f12f::25]:443 (ESTABLISHED)
loopd       5    sam   3u   IPv4 0x4 0t0  TCP 127.0.0.1:5000->127.0.0.1:5001 (ESTABLISHED)
local       6    sam   3u   IPv4 0x5 0t0  TCP 192.168.1.4:22->192.168.1.9:51000 (ESTABLISHED)
listener    7    sam   3u   IPv4 0x6 0t0  TCP *:8080 (LISTEN)
"""


class SnapshotTest(unittest.TestCase):
    def test_parses_remote_connections_and_drops_local_ones(self):
        flows = n.snapshot(run=lambda: LSOF)
        ips = sorted(f["ip"] for f in flows)
        self.assertEqual(ips, ["104.18.39.21", "140.82.112.26", "2a03:2880:f12f::25"])
        self.assertNotIn("127.0.0.1", ips)        # loopback dropped
        self.assertNotIn("192.168.1.9", ips)      # private LAN dropped
        google = [f for f in flows if f["ip"] == "104.18.39.21"][0]
        self.assertEqual(google["app"], "Google")   # \\x20 unescaped, trailing space stripped
        self.assertEqual(google["port"], 443)


class GeoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = n.Geo()

    def test_ipv4_locates_to_a_country(self):
        for ip in ("104.18.39.21", "8.8.8.8", "140.82.112.26"):
            place = self.geo.locate(ip)
            self.assertIsNotNone(place["lat"], ip)
            self.assertTrue(place["country"], ip)

    def test_ipv6_locates_to_a_country(self):
        place = self.geo.locate("2a03:2880:f12f::25")   # a real Meta range
        self.assertIsNotNone(place["lat"])
        self.assertTrue(place["country"])

    def test_unroutable_ip_is_unknown_not_a_crash(self):
        self.assertEqual(self.geo.locate("not-an-ip"), None)
        place = self.geo.locate("240.0.0.1")            # reserved, unallocated
        self.assertIsNone(place["lat"])

    def test_known_ranges(self):
        self.assertEqual(self.geo.known_org("104.18.39.21"), "Cloudflare")
        self.assertEqual(self.geo.known_org("140.82.112.26"), "GitHub")


class ClassifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = n.Watcher(n.Geo())

    def test_org_from_hostname(self):
        self.assertEqual(self.w.classify("1.2.3.4", "server-1.1e100.net")[0], "Google")
        self.assertEqual(self.w.classify("1.2.3.4", "ec2-x.compute.amazonaws.com")[0], "Amazon AWS")

    def test_trackers_are_flagged(self):
        org, is_tracker, name = self.w.classify("1.2.3.4", "pagead.doubleclick.net")
        self.assertTrue(is_tracker)
        self.assertIn("DoubleClick", name)
        self.assertFalse(self.w.classify("1.2.3.4", "cdn.example.com")[1])

    def test_org_falls_back_to_known_range_then_domain(self):
        self.assertEqual(self.w.classify("104.18.39.21", "")[0], "Cloudflare")   # no PTR, but known range
        self.assertEqual(self.w.classify("9.9.9.9", "dns9.quad9.net")[0], "quad9.net")


class EnrichTest(unittest.TestCase):
    def test_enrich_locates_classifies_and_counts(self):
        w = n.Watcher(n.Geo())
        w.hosts = {"104.18.39.21": "", "140.82.112.26": "lb.github.com", "2a03:2880:f12f::25": "edge.facebook.com"}
        flows = w.enrich(n.snapshot(run=lambda: LSOF))
        by_ip = {f["ip"]: f for f in flows}
        self.assertEqual(by_ip["140.82.112.26"]["org"], "GitHub")
        self.assertTrue(by_ip["2a03:2880:f12f::25"]["tracker"])       # facebook host -> tracker
        self.assertTrue(by_ip["104.18.39.21"]["country"])

    def test_report_summary_counts(self):
        geo = n.Geo(); w = n.Watcher(geo)
        w.hosts = {"104.18.39.21": "cdn.example.com", "140.82.112.26": "x.github.com",
                   "2a03:2880:f12f::25": "edge.facebook.com"}
        data = n.report(geo, w, {"name": "Testland", "lat": 0, "lon": 0},
                        snap=lambda: n.snapshot(run=lambda: LSOF))
        self.assertEqual(data["summary"]["connections"], 3)
        self.assertEqual(data["summary"]["trackers"], 1)
        self.assertGreaterEqual(data["summary"]["countries"], 1)


class SafetyTest(unittest.TestCase):
    def test_globe_page_has_no_unfilled_placeholder(self):
        page = (ROOT / "globe.html").read_text()
        self.assertIn("/*__CONFIG__*/null", page)   # the server replaces this; it must be present to replace

    def test_home_country_from_locale(self):
        self.assertEqual(n.home_country("np"), "NP")
        self.assertEqual(n.home_country("US"), "US")


if __name__ == "__main__":
    unittest.main()
