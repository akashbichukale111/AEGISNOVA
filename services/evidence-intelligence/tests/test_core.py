import json, threading, unittest, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from evidence_intel.core import Service, validate, ValidationError, redact, applicability, canon_url, bad
from evidence_intel.fixtures import FixtureHTTP, DEMO_ENV
from evidence_intel.server import serve

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
class Clock:
    def __init__(s): s.t = T0
    def __call__(s): return s.t
REQ = {"ecosystem": "PyPI", "package": "demo-lib", "version": "1.1.0"}
def svc(clock=None, env=DEMO_ENV, **kw): return Service(http=FixtureHTTP(**kw), env=env, clock=clock or Clock(), demo=True)

class T(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(validate(REQ)["package"], "demo-lib")
        for bad_req in ({}, {"ecosystem": "X", "package": "a"}, {"ecosystem": "PyPI", "package": "a b;"}, {"advisory_id": "no"}, {"advisory_id": "CVE-2099-0001", "sources": ["evil"]}, "x"):
            with self.assertRaises(ValidationError): validate(bad_req)
        self.assertEqual(validate({"advisory_id": "cve-2099-0001"})["advisory_id"], "CVE-2099-0001")
    def test_bundle_provenance_citations_hash(self):
        b = svc().research(REQ)
        self.assertEqual([r["citation"] for r in b["records"]], ["SRC-001", "SRC-002", "SRC-003"])
        self.assertEqual(b["reconciliation"]["overall"], "CORROBORATED")
        for r in b["records"]: self.assertEqual(len(r["content_hash"]), 64); self.assertTrue(r["retrieved_at"]); self.assertTrue(r["url"].startswith("http"))
        b2 = svc().research(REQ); self.assertEqual(b["snapshot_hash"], b2["snapshot_hash"])
        tav = [r for r in b["records"] if r["provider"] == "tavily"][0]
        self.assertEqual(tav["url"], "https://blog.example.org/demo-lib"); self.assertIn("relevance only", " ".join(tav["limitations"]))
        json.dumps(b)
    def test_aliases_grouped_and_mirror_not_independent(self):
        b = svc().research(REQ); g = [x for x in b["reconciliation"]["groups"] if x["group_id"] != "discovery"]
        self.assertEqual(len(g), 1); self.assertIn("CVE-2099-0001", g[0]["ids"])
        b = svc(osv_id="GHSA-abcd-efgh-ijkl").research(REQ)
        self.assertEqual(b["reconciliation"]["overall"], "CONSISTENT")
    def test_conflicts_preserved(self):
        b = svc(osv_fixed="1.2.4", ghsa_fixed="1.3.0", ghsa_sev="low").research(REQ)
        self.assertEqual(b["reconciliation"]["overall"], "CONFLICTING")
        f = {c["field"]: c["values"] for c in b["reconciliation"]["groups"][0]["conflicts"]}
        self.assertEqual(sorted(sum(f["fixed_versions"].values(), [])), ["1.2.4", "1.3.0"]); self.assertIn("severity", f)
        self.assertLessEqual(b["quality"]["indicator"], 70)
    def test_applicability(self):
        b = svc().research(REQ); osv = [r for r in b["records"] if r["provider"] == "osv"][0]
        self.assertEqual(applicability(osv, {"version": "1.1.0"}), "IN_LISTED_RANGE"); self.assertEqual(applicability(osv, {"version": "1.2.4"}), "NOT_IN_LISTED_RANGES")
        self.assertEqual(applicability(osv, {"version": "1.0rc1"}), "NOT_EVALUATED"); self.assertEqual(applicability(osv, {}), "NOT_EVALUATED")
    def test_missing_credentials_partial(self):
        b = svc(env={}).research(REQ)
        self.assertEqual(b["providers"]["tavily"]["status"], "NOT_CONFIGURED"); self.assertEqual(b["providers"]["osv"]["status"], "OK"); self.assertEqual(len(b["records"]), 2)
    def test_provider_failures(self):
        b = svc(fail={"tavily": "timeout", "osv": 429, "ghsa": 401}).research(REQ)
        self.assertEqual([b["providers"][n]["status"] for n in ("tavily", "osv", "ghsa")], ["TIMEOUT", "RATE_LIMITED", "AUTH_ERROR"])
        self.assertEqual(b["reconciliation"]["overall"], "INSUFFICIENT_EVIDENCE"); self.assertIn("not evidence of safety", b["recommended_next_action"])
        self.assertEqual(svc(fail={"ghsa": 500}).research(REQ)["providers"]["ghsa"]["status"], "ERROR"); self.assertEqual(bad(404), None)
    def test_empty_never_safe(self):
        b = svc().research.__self__.__class__(http=FixtureHTTP(empty=True), env=DEMO_ENV, clock=Clock()).research(REQ)
        self.assertTrue(all(p["status"] == "EMPTY" for p in b["providers"].values())); self.assertEqual(b["reconciliation"]["overall"], "INSUFFICIENT_EVIDENCE")
        self.assertNotIn('"safe"', json.dumps(b["reconciliation"]).lower()); self.assertTrue(any("safe" in l for l in b["limitations"]))
    def test_freshness_thresholds_and_dates(self):
        c = Clock(); s = svc(c); b = s.research(REQ); self.assertEqual(b["freshness"]["overall"], "DATE_UNKNOWN")  # undated Tavily record is worst
        tav = [r for r in b["records"] if r["provider"] == "tavily"][0]; self.assertEqual(b["freshness"]["per_record"][tav["citation"]], "DATE_UNKNOWN")
        for hrs, exp in ((30, "AGING"), (100, "STALE"), (300, "EXPIRED")):
            from evidence_intel.core import freshness, DEFAULTS
            f = freshness([dict(r, last_validated_at=(T0).strftime("%Y-%m-%dT%H:%M:%SZ")) for r in b["records"] if r["provider"] == "osv"], b["providers"], T0 + timedelta(hours=hrs), DEFAULTS, set())
            self.assertEqual(f["overall"], exp)
    def test_refresh_unchanged_changed_unavailable(self):
        c = Clock(); h = FixtureHTTP(); s = Service(http=h, env=DEMO_ENV, clock=c, demo=True); b = s.research(REQ); rid = b["research_id"]
        c.t += timedelta(hours=1); r1 = s.refresh(rid); self.assertEqual(r1["diff"]["overall"], "UNCHANGED"); self.assertEqual(s.diff(rid)["overall"], "UNCHANGED")
        h.c["osv_fixed"] = "1.2.9"; c.t += timedelta(hours=1); r2 = s.refresh(rid)
        self.assertEqual(r2["diff"]["providers"]["osv"]["state"], "MATERIAL_CHANGE"); self.assertEqual(r2["freshness"]["overall"], "CHANGED")
        self.assertTrue(any(ch["field"] == "fixed_versions" for ch in sum(r2["diff"]["providers"]["osv"]["changed"].values(), [])))
        h.c["fail"] = {"osv": "timeout"}; c.t += timedelta(hours=1); r3 = s.refresh(rid)
        self.assertEqual(r3["diff"]["providers"]["osv"]["state"], "SOURCE_UNAVAILABLE"); self.assertTrue(r3["providers"]["osv"]["carried_over"])
        self.assertEqual([x for x in r3["records"] if x["provider"] == "osv"][0]["fixed_versions"], ["1.2.9"]); self.assertEqual(r3["freshness"]["overall"], "SOURCE_UNAVAILABLE")
        self.assertEqual(s.get(rid)["snapshot_seq"], 4)
    def test_uncomparable(self):
        c = Clock(); h = FixtureHTTP(fail={"osv": 500}); s = Service(http=h, env=DEMO_ENV, clock=c, demo=True); rid = s.research(REQ)["research_id"]
        h.c["fail"] = {}; self.assertEqual(s.refresh(rid)["diff"]["providers"]["osv"]["state"], "UNCOMPARABLE")
    def test_redaction_and_untrusted(self):
        self.assertNotIn("ghp_abc123", redact("fail ghp_abc123 Bearer tvly-xyz")); self.assertNotIn("tvly-xyz", redact("Bearer tvly-xyz"))
        s = svc(); self.assertNotIn("demo-fixture-not-a-real-key", json.dumps(s.settings())); b = s.research(REQ)
        tav = [r for r in b["records"] if r["provider"] == "tavily"][0]; self.assertTrue(tav["untrusted"])
        self.assertNotIn("9.9.9", json.dumps(b["reconciliation"])); self.assertEqual(b["reconciliation"]["groups"][-1]["state"], "UNRESOLVED")
        self.assertEqual(canon_url("javascript:alert(1)"), "")
    def test_export_and_evidence_lookup(self):
        s = svc(); b = s.research(REQ); e = s.export(b["research_id"]); self.assertEqual(e["bundle"]["schema"], "aegisnova.evidence-bundle/1")
        self.assertEqual(s.evidence(b["records"][0]["evidence_id"])["citation"], "SRC-001")
        with self.assertRaises(KeyError): s.get("R-none")
    def test_http_end_to_end(self):
        s = svc(); srv = serve(s, port=0); port = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start(); u = f"http://127.0.0.1:{port}"
        def call(p, body=None, m=None):
            rq = urllib.request.Request(u + p, data=json.dumps(body).encode() if body is not None else None, method=m or ("POST" if body is not None else "GET"))
            try:
                with urllib.request.urlopen(rq) as r: return r.status, r.read()
            except urllib.error.HTTPError as e: return e.code, e.read()
        try:
            self.assertEqual(call("/health")[0], 200); self.assertIn(b"Evidence Intelligence", call("/")[1])
            st, raw = call("/api/v1/research", REQ); self.assertEqual(st, 201); rid = json.loads(raw)["research_id"]
            self.assertEqual(call("/api/v1/research", {"package": "x"})[0], 400)
            self.assertEqual(call(f"/api/v1/research/{rid}/refresh", {}, "POST")[0], 200)
            self.assertEqual(json.loads(call(f"/api/v1/research/{rid}/diff")[1])["overall"], "UNCHANGED")
            self.assertEqual(json.loads(call(f"/api/v1/research/{rid}/export")[1])["bundle"]["snapshot_seq"], 2)
            self.assertEqual(call("/api/v1/research/R-nope")[0], 404); self.assertEqual(call("/../core.py")[0], 404)
            self.assertIn("providers", json.loads(call("/api/v1/providers/health")[1]))
        finally: srv.shutdown()
if __name__ == "__main__": unittest.main()
