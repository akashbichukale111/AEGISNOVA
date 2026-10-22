import datetime as dt, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ira import core, warranty
HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); REPOS = os.path.join(HOME, "fixtures", "repos"); SAMPLE = os.path.join(REPOS, "sample")
def patch(n): return open(os.path.join(HOME, "fixtures", "patches", n)).read()
BASE = core.tree_hash(SAMPLE)

class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.tmp = tempfile.mkdtemp(); os.environ["IRA_TMP_ROOT"] = self.tmp; os.environ["IRA_ALLOW_LOCAL_EXEC"] = "1"
    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True); shutil.rmtree(self.tmp, ignore_errors=True); os.environ.pop("IRA_ALLOW_LOCAL_EXEC", None); os.environ.pop("IRA_TMP_ROOT", None)
    def run_(self, p, **kw):
        req = {"repo": "sample", "base_sha": BASE, "patch": p, "claim": {"summary": "fix", "tests_passed": True}}; req.update(kw); return core.assess(req, self.d, REPOS)

class TestIntake(Base):
    def test_malformed(self): self.assertEqual(self.run_(patch("malformed.diff"))["error"]["code"], "MALFORMED")
    def test_traversal(self): self.assertEqual(self.run_(patch("traversal.diff"))["error"]["code"], "PATH_TRAVERSAL")
    def test_absolute(self): self.assertEqual(self.run_(patch("absolute.diff"))["error"]["code"], "PATH_ABSOLUTE")
    def test_forbidden(self):
        R = self.run_("--- a/.env\n+++ b/.env\n@@ -1,1 +1,1 @@\n-a\n+b\n"); self.assertEqual(R["error"]["code"], "FORBIDDEN_PATH"); self.assertEqual(R["status"], "REJECTED")
    def test_oversized(self): self.assertEqual(self.run_(patch("good.diff") + "x" * 300000)["error"]["code"], "PATCH_TOO_LARGE")
    def test_binary(self): self.assertEqual(self.run_("Binary files a/x and b/x differ\n")["error"]["code"], "BINARY_REJECTED")
    def test_base_mismatch(self):
        R = self.run_(patch("good.diff"), base_sha="0" * 64); self.assertEqual(R["status"], "BLOCKED"); self.assertEqual(R["error"]["code"], "BASE_MISMATCH"); self.assertEqual(R["tests"], {})
    def test_does_not_apply(self): self.assertEqual(self.run_(patch("good.diff").replace("return a / b", "return a // b"))["error"]["code"], "DOES_NOT_APPLY")
    def test_rejected_still_has_proof(self): R = self.run_(patch("malformed.diff")); self.assertTrue(core.verify_proof(R["proof"]))

class TestWarrant(unittest.TestCase):
    def ctx(self, **o): c = {"repo_id": "sample", "base_sha": BASE, "patch_hash": "p1", "paths": ["calc.py"], "action": "test_execution"}; c.update(o); return c
    def w(self, **o): return core.make_test_warrant("sample", BASE, "p1", ["calc.py"], **o)
    def test_missing(self): self.assertEqual(core.check_warrant(None, self.ctx())["status"], "NO_WARRANT")
    def test_valid(self): self.assertEqual(core.check_warrant(self.w(), self.ctx())["status"], "VALID")
    def test_expired(self): self.assertEqual(core.check_warrant(self.w(ttl_s=-5), self.ctx())["status"], "EXPIRED")
    def test_revoked(self): w = self.w(); self.assertEqual(core.check_warrant(w, self.ctx(), revoked={w["warrant_id"]})["status"], "REVOKED")
    def test_changed_patch(self): self.assertEqual(core.check_warrant(self.w(), self.ctx(patch_hash="p2"))["status"], "MISMATCH")
    def test_scope(self): self.assertEqual(core.check_warrant(self.w(), self.ctx(paths=["other.py"]))["status"], "MISMATCH")
    def test_overbroad(self): self.assertEqual(core.check_warrant(core.make_test_warrant("sample", BASE, "p1", ["*"]), self.ctx())["status"], "OVER_BROAD")
    def test_tamper(self): w = self.w(); w["path_scope"] = ["calc.py", "x.py"]; self.assertEqual(core.check_warrant(w, self.ctx())["status"], "BAD_MAC")
    def test_malformed(self): self.assertEqual(core.check_warrant({"warrant_id": "x"}, self.ctx())["status"], "MALFORMED")
    def test_action(self): self.assertEqual(core.check_warrant(self.w(actions=("static",)), self.ctx())["status"], "MISMATCH")

class TestPipeline(Base):
    def test_good_patch_verified_with_warnings(self):
        R = self.run_(patch("good.diff"), demo_warrant=True)
        self.assertEqual(R["tests"]["before"]["status"], "FAILED"); self.assertEqual(R["tests"]["after"]["status"], "PASSED")
        self.assertEqual(R["status"], "VERIFIED_WITH_WARNINGS"); self.assertEqual(R["breaker"]["status"], "BREAK_FOUND")  # only MEDIUM: no tests added
        self.assertTrue(R["warranty_id"]); self.assertTrue(any(f["id"] == "A-BEFORE-AFTER" and "demonstrated" in f["observed"] for f in R["audit"]["findings"]))
        self.assertEqual([s["stage"] for s in R["stages"]], core.STAGES)
    def test_no_warrant_not_run_and_claim_untrusted(self):
        R = self.run_(patch("good.diff")); self.assertEqual(R["tests"]["after"]["status"], "NOT_RUN"); self.assertEqual(R["status"], "NEEDS_HUMAN_REVIEW")
        self.assertEqual(R["audit"]["status"], "DISCREPANCIES"); self.assertIn("NOT trusted", [f for f in R["audit"]["findings"] if f["id"] == "A-CLAIM-TESTS"][0]["observed"])
        self.assertIn(R["risk"]["overall"], ("HIGH", "UNKNOWN"))
    def test_sandbox_unavailable_blocks(self):
        os.environ.pop("IRA_ALLOW_LOCAL_EXEC"); R = self.run_(patch("good.diff"), demo_warrant=True)
        self.assertEqual(R["tests"]["after"]["status"], "BLOCKED"); self.assertEqual(R["status"], "BLOCKED"); self.assertNotIn("PASSED", [R["tests"]["after"]["status"]])
    def test_failing_patch_rejected(self):
        R = self.run_(patch("swallow_error.diff"), demo_warrant=True); self.assertEqual(R["tests"]["after"]["status"], "FAILED"); self.assertEqual(R["status"], "REJECTED"); self.assertEqual(R["risk"]["overall"], "CRITICAL"); self.assertIsNone(R["warranty_id"])
    def test_breaker_seeded_defect_and_skips(self):
        R = self.run_(patch("weakened_tests.diff"), demo_warrant=True); rules = {f["rule"] for f in R["breaker"]["findings"]}
        self.assertIn("ERROR_SWALLOWED", rules); self.assertIn("TEST_WEAKENED", rules); self.assertEqual(R["tests"]["after"]["summary"]["skipped"], 1)
        self.assertEqual(R["status"], "NEEDS_HUMAN_REVIEW"); self.assertTrue(any(f["id"] == "A-SKIPPED" for f in R["audit"]["findings"]))
    def test_mismatched_warrant_blocks(self):
        w = core.make_test_warrant("sample", BASE, "deadbeef", ["calc.py"]); R = self.run_(patch("good.diff"), warrant=w)
        self.assertEqual(R["warrant"]["status"], "MISMATCH"); self.assertEqual(R["tests"]["after"]["status"], "NOT_RUN"); self.assertEqual(R["status"], "BLOCKED")
    def test_cleanup_and_offline(self):
        self.run_(patch("good.diff"), demo_warrant=True); self.assertEqual(os.listdir(self.tmp), [])
        for k in os.environ:
            self.assertNotIn("KEY", k.upper() if k.startswith("IRA_") else "")

class TestRunner(Base):
    def test_timeout_and_kill(self):
        c = ["python3", "-c", "import time;time.sleep(30)"]; r = core.run_cmd(c, self.tmp, timeout=1, allowed=[c]); self.assertTrue(r["timed_out"]); self.assertEqual(r["status"], "INCONCLUSIVE"); self.assertLess(r["duration_s"], 10)
    def test_allowlist(self): self.assertEqual(core.run_cmd(["rm", "-rf", "/"], self.tmp)["status"], "BLOCKED")
    def test_redaction_and_env_filter(self):
        os.environ["IRA_SECRET_PROBE"] = "supersecretvalue123"
        c = ["python3", "-c", "import os;print(os.environ.get('IRA_SECRET_PROBE'));print('password=\"hunter2hunter2\"')"]; r = core.run_cmd(c, self.tmp, allowed=[c]); os.environ.pop("IRA_SECRET_PROBE")
        self.assertNotIn("supersecretvalue123", r["output"]); self.assertNotIn("hunter2hunter2", r["output"]); self.assertIn("None", r["output"])
    def test_inconclusive_when_no_tests(self): self.assertEqual(core.parse_unittest("Ran 0 tests", 0, False)[0], "INCONCLUSIVE")

class TestProof(Base):
    def test_hash_stable_and_sensitive(self):
        R = self.run_(patch("good.diff"), demo_warrant=True); p = R["proof"]; self.assertTrue(core.verify_proof(p)); self.assertEqual(core.proof_hash(p), p["proof_hash"])
        q = json.loads(json.dumps(p)); q["overall_status"] = "VERIFIED"; self.assertFalse(core.verify_proof(q))
        q = json.loads(json.dumps(p)); q["commands_executed"][1]["exit_code"] = 1; self.assertFalse(core.verify_proof(q))
        self.assertEqual(p["attestation"]["type"], "none"); self.assertIn("NOT a digital signature", p["attestation"]["note"])
    def test_export_preserves_evidence_and_limits(self):
        R = self.run_(patch("good.diff"), demo_warrant=True); e = core.export_proof(R)
        for ev in e["evidence"]: self.assertEqual(core.sha(e["evidence_content"][ev["ref"]]["content"]), ev["sha256"])
        self.assertTrue(e["limitations"]); self.assertIn("DEMO", core.render_report(R))
    def test_hmac_attestation_optional(self):
        os.environ["IRA_PROOF_HMAC_KEY"] = "k"; 
        try: R = self.run_(patch("malformed.diff")); self.assertEqual(R["proof"]["attestation"]["type"], "hmac-sha256")
        finally: os.environ.pop("IRA_PROOF_HMAC_KEY")

class TestWarranty(Base):
    def test_lifecycle(self):
        R = self.run_(patch("good.diff"), demo_warrant=True); w = warranty.load(self.d, R["warranty_id"]); snap = warranty.snapshot_dir(self.d, w["warranty_id"]); t0 = dt.datetime.now(dt.timezone.utc)
        self.assertEqual(warranty.evaluate(w, snap)["state"], "ACTIVE")
        self.assertEqual(warranty.evaluate(w, snap, when=t0 + dt.timedelta(days=20))["state"], "AGING")
        r = warranty.revalidate(w, snap, self.d, when=t0 + dt.timedelta(days=20)); self.assertEqual(r["state"], "ACTIVE"); self.assertEqual(r["revalidation"]["status"], "PASSED")
        self.assertEqual(warranty.evaluate(w, snap, add_triggers=["dependency_advisory"])["state"], "REQUIRES_REVALIDATION")
        r = warranty.revalidate(w, snap, self.d); self.assertEqual(r["state"], "ACTIVE")  # recovery after passing recheck
        self.assertEqual(warranty.evaluate(w, snap, when=t0 + dt.timedelta(days=31))["state"], "EXPIRED")
        self.assertEqual(w["proof_id"], R["proof"]["proof_id"]); self.assertGreaterEqual(len(w["history"]), 5)
    def test_covered_file_change_invalidates(self):
        R = self.run_(patch("good.diff"), demo_warrant=True); w = warranty.load(self.d, R["warranty_id"]); cp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, cp, True)
        shutil.copytree(warranty.snapshot_dir(self.d, w["warranty_id"]), cp, dirs_exist_ok=True); open(os.path.join(cp, "calc.py"), "a").write("# tamper\n")
        w = warranty.evaluate(w, cp); self.assertEqual(w["state"], "INVALIDATED"); self.assertIn("calc.py", w["history"][-1]["reason"])
        self.assertEqual(warranty.evaluate(w, warranty.snapshot_dir(self.d, w["warranty_id"]))["state"], "INVALIDATED")  # sticky
    def test_patch_hash_and_source_unavailable_and_failed_recheck(self):
        R = self.run_(patch("good.diff"), demo_warrant=True)
        w = warranty.load(self.d, R["warranty_id"]); self.assertEqual(warranty.evaluate(w, patch_hash="other")["state"], "INVALIDATED")
        w = warranty.load(self.d, R["warranty_id"]); self.assertEqual(warranty.evaluate(w, "/nonexistent/x")["state"], "SOURCE_UNAVAILABLE")
        w = warranty.load(self.d, R["warranty_id"]); cp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, cp, True)
        shutil.copytree(warranty.snapshot_dir(self.d, w["warranty_id"]), cp, dirs_exist_ok=True)
        t = os.path.join(cp, "tests", "test_calc.py"); open(t, "a").write("\n    def test_new(self):\n        self.fail('x')\n")
        r = warranty.revalidate(w, cp, self.d); self.assertEqual(r["revalidation"]["status"], "FAILED"); self.assertEqual(r["state"], "REQUIRES_REVALIDATION"); self.assertEqual(r["proof_id"], R["proof"]["proof_id"])

class TestAPI(Base):
    def test_http(self):
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        from ira import server, cli
        cli.DATA = self.d; srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=srv.serve_forever, daemon=True).start(); u = f"http://127.0.0.1:{srv.server_port}"
        try:
            self.assertTrue(json.load(urllib.request.urlopen(u + "/v1/health"))["offline_ok"])
            req = urllib.request.Request(u + "/v1/runs", json.dumps({"repo": "sample", "base_sha": BASE, "patch": patch("good.diff"), "demo_warrant": True}).encode(), {"Content-Type": "application/json"})
            R = json.load(urllib.request.urlopen(req)); self.assertEqual(R["status"], "VERIFIED_WITH_WARNINGS")
            self.assertIn("REPAIR PROOF", urllib.request.urlopen(u + f"/v1/runs/{R['run_id']}/proof/report").read().decode())
            try: urllib.request.urlopen(u + "/v1/runs/run_000000000000"); self.fail()
            except urllib.error.HTTPError as e: self.assertEqual(json.load(e)["error"]["code"], "NOT_FOUND")
            big = urllib.request.Request(u + "/v1/runs", b"{" + b" " * 1_100_000 + b"}")
            try: urllib.request.urlopen(big); self.fail()
            except urllib.error.HTTPError as e: self.assertEqual(e.code, 413)
            except urllib.error.URLError: pass  # server closed connection after rejecting oversize body (fail closed)
        finally: srv.shutdown()
if __name__ == "__main__": unittest.main()
