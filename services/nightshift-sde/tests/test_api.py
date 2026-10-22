"""HTTP API contract tests: a real ThreadingHTTPServer on an ephemeral port, real tokens, real SQLite. TEST DATA only."""
import http.client
import json
import threading
import unittest

from nightshift.server import create_server
from tests.helpers import Env

TOK = {"viewer": "test-viewer-token-not-a-secret", "operator": "test-operator-token-not-a-secret",
       "approver": "test-approver-token-not-a-secret", "admin": "test-admin-token-not-a-secret"}


class ApiBase(unittest.TestCase):
    env_kwargs: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.env = Env(**cls.env_kwargs)
        cls.srv = create_server(cls.env.app, "127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.env.close()

    def call(self, method, path, body=None, role="admin", headers=None, raw=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = dict(headers or {})
        tok = token if token is not None else (TOK[role] if role else None)
        if tok:
            h["Authorization"] = "Bearer " + tok
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        payload = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
        conn.close()
        try:
            return r.status, json.loads(payload) if payload else None, hdrs
        except ValueError:
            return r.status, payload, hdrs


class AuthAndEnvelopeTests(ApiBase):
    def test_health_is_public_and_minimal(self):
        s, b, h = self.call("GET", "/api/health", role=None)
        self.assertEqual(s, 200)
        self.assertEqual(set(b), {"status", "version", "time"})

    def test_missing_or_bad_token_is_401_with_consistent_error_envelope_and_correlation_id(self):
        for tok in (None, "wrong-token-value"):
            s, b, h = self.call("GET", "/api/overview", role=None, token=tok)
            self.assertEqual(s, 401)
            self.assertEqual(set(b["error"]), {"code", "message", "details", "correlation_id"})
            self.assertEqual(b["error"]["correlation_id"], h["x-correlation-id"])

    def test_client_supplied_correlation_id_is_echoed_and_hostile_ones_replaced(self):
        s, b, h = self.call("GET", "/api/me", headers={"X-Correlation-ID": "corr-from-client-123"})
        self.assertEqual(h["x-correlation-id"], "corr-from-client-123")
        s, b, h = self.call("GET", "/api/me", headers={"X-Correlation-ID": "bad id <script>x</script> injected"})
        self.assertNotIn("injected", json.dumps(h).lower())
        self.assertTrue(h["x-correlation-id"].startswith("corr_"))

    def test_roles_and_permissions(self):
        for role, perms in (("viewer", {"read"}), ("operator", {"read", "operate"}), ("approver", {"read", "approve", "authorize_repair"}),
                            ("admin", {"read", "operate", "approve", "authorize_repair", "admin"})):
            s, b, _ = self.call("GET", "/api/me", role=role)
            self.assertEqual((s, set(b["permissions"])), (200, perms), role)

    def test_viewer_cannot_mutate(self):
        rid = self.env.repo("legacy-batch")["id"]
        for method, path, body in (("POST", f"/api/repos/{rid}/trigger", {}), ("POST", "/api/schedules", {}), ("POST", "/api/scheduler/tick", None),
                                   ("PATCH", f"/api/repos/{rid}", {"name": "x"}), ("POST", "/api/approvals/x/approve", {})):
            s, b, _ = self.call(method, path, body, role="viewer")
            self.assertEqual(s, 403, (method, path))
            self.assertEqual(b["error"]["code"], "FORBIDDEN")

    def test_security_headers_on_api_and_static(self):
        s, _, h = self.call("GET", "/api/me")
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["cache-control"], "no-store")
        s, body, h = self.call("GET", "/", role=None)
        self.assertEqual(s, 200)
        csp = h["content-security-policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn(b"NightShift", body)

    def test_unknown_endpoint_method_and_static_traversal(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        self.assertEqual(self.call("DELETE", "/api/overview")[0], 405)
        for p in ("/ui/../nightshift/config.py", "/ui/%2e%2e/nightshift/config.py", "/etc/passwd", "/ui/../../etc/passwd"):
            s, _, _ = self.call("GET", p, role=None)
            self.assertEqual(s, 404, p)

    def test_input_validation_and_limits(self):
        rid = self.env.repo("legacy-batch")["id"]
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", raw=b"{not json", headers={"Content-Type": "application/json"})
        self.assertEqual((s, b["error"]["code"]), (400, "INVALID_JSON"))
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", raw=b"[]", headers={"Content-Type": "application/json"})
        self.assertEqual(s, 400)
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", raw=b"{}", headers={"Content-Type": "text/plain"})
        self.assertEqual((s, b["error"]["code"]), (400, "UNSUPPORTED_MEDIA_TYPE"))
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", raw=b"x" * (300 * 1024), headers={"Content-Type": "application/json"})
        self.assertEqual((s, b["error"]["code"]), (413, "PAYLOAD_TOO_LARGE"))
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", {"allow_repair": "yes"})
        self.assertEqual(s, 400)
        s, b, _ = self.call("GET", "/api/jobs?limit=abc")
        self.assertEqual(s, 400)

    def test_arbitrary_paths_and_commands_cannot_be_registered(self):
        for rel in ("../../etc", "/etc", "demo/does-not-exist"):
            s, b, _ = self.call("POST", "/api/repos", {"name": "x", "slug": "x/y", "rel_path": rel})
            self.assertEqual((s, b["error"]["code"]), (400, "INVALID_REPO_PATH"), rel)
        s, b, _ = self.call("POST", "/api/repos", {"name": "x", "slug": "x/y", "rel_path": "demo/legacy-batch", "test_command_key": "rm -rf /"})
        self.assertEqual((s, b["error"]["code"]), (400, "INVALID_TEST_COMMAND"))
        s, b, _ = self.call("POST", "/api/repos", {"name": "x", "slug": "x/y", "rel_path": "demo/legacy-batch", "test_command": ["sh"]})
        self.assertEqual((s, b["error"]["code"]), (400, "UNKNOWN_FIELD"))


class JobApiTests(ApiBase):
    def test_trigger_is_idempotent_and_job_detail_has_the_documented_shape(self):
        rid = self.env.repo("legacy-batch")["id"]
        s1, b1, _ = self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": "api-key-0001-abcd"})
        s2, b2, _ = self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": "api-key-0001-abcd"})
        self.assertEqual((s1, b1["created"], s2, b2["created"]), (201, True, 200, False))
        self.assertEqual(b1["job"]["id"], b2["job"]["id"])
        jid = b1["job"]["id"]
        self.env.drain()
        s, d, _ = self.call("GET", f"/api/jobs/{jid}", role="operator")
        self.assertEqual(s, 200)
        for key in ("job", "brief", "transitions", "attempts", "checkpoints", "resume", "lease", "stage_durations_seconds", "approvals",
                    "risk_assessments", "findings", "evidence", "artifacts", "notifications", "explanation", "actions", "server_time"):
            self.assertIn(key, d)
        self.assertTrue(all({"from_state", "to_state", "at", "actor", "reason_code", "attempt", "correlation_id"} <= set(t) for t in d["transitions"]))
        acts = {a["action"]: a for a in d["actions"]}
        self.assertFalse(acts["cancel"]["enabled"])  # already finished
        self.assertTrue(acts["replay"]["enabled"])
        s, d2, _ = self.call("GET", f"/api/jobs/{jid}", role="viewer")
        viewer_acts = {a["action"]: a for a in d2["actions"]}
        self.assertFalse(viewer_acts["replay"]["enabled"])  # viewer sees disabled controls WITH a reason
        self.assertIn("permission", viewer_acts["replay"]["reason"])

    def test_listing_filters_and_pagination(self):
        rid = self.env.repo("legacy-batch")["id"]
        for i in range(3):
            self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": f"page-key-{i:04d}-abc"})
        s, b, _ = self.call("GET", f"/api/jobs?repo_id={rid}&limit=2&offset=0")
        self.assertEqual((s, len(b["items"])), (200, 2))
        self.assertGreaterEqual(b["total"], 3)
        self.assertIsNotNone(b["next_offset"])
        s, b2, _ = self.call("GET", f"/api/jobs?repo_id={rid}&limit=2&offset={b['next_offset']}")
        self.assertFalse({i["id"] for i in b["items"]} & {i["id"] for i in b2["items"]})
        s, b3, _ = self.call("GET", "/api/jobs?state=NOPE")
        self.assertEqual((s, b3["total"]), (200, 0))
        s, b4, _ = self.call("GET", "/api/jobs?limit=100000")
        self.assertLessEqual(b4["limit"], 100)

    def test_safe_actions_and_invalid_transition_rejected_server_side(self):
        rid = self.env.repo("legacy-batch")["id"]
        _, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": "act-key-0001-abcd"})
        jid = b["job"]["id"]
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/pause", {}, role="operator")
        self.assertEqual((s, r["state"]), (200, "PAUSED"))
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/retry", {}, role="operator")
        self.assertEqual(s, 409)  # only RETRY_WAIT jobs can skip backoff
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/resume", {}, role="operator")
        self.assertEqual((s, r["state"]), (200, "QUEUED"))
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/cancel", {}, role="operator")
        self.assertEqual((s, r["state"]), (200, "CANCELLED"))
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/cancel", {}, role="operator")
        self.assertEqual((s, r["error"]["code"]), (409, "JOB_TERMINAL"))
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/explode", {}, role="operator")
        self.assertEqual(s, 400)
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/replay", {"allow_repair": True}, role="operator")
        self.assertEqual(s, 403)  # replay cannot escalate to write-capable work
        s, r, _ = self.call("POST", f"/api/jobs/{jid}/replay", {}, role="operator")
        self.assertEqual((s, r["replay_of"]), (201, jid))
        s, r, _ = self.call("GET", "/api/jobs/job_doesnotexist")
        self.assertEqual((s, r["error"]["code"]), (404, "JOB_NOT_FOUND"))

    def test_trigger_rate_limit_returns_429_with_retry_after(self):
        self.env.clock.advance(120)  # fresh fixed-window for the limiter (fake clock never advances on its own)
        self.env.settings.trigger_rate_limit_per_minute = 2
        rid = self.env.repo("conflict-lab")["id"]
        codes = [self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": f"rl-key-{i:04d}-abcd"})[0] for i in range(4)]
        self.assertEqual(codes[:2], [201, 201])
        self.assertIn(429, codes)
        s, b, h = self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": "rl-key-9999-abcd"})
        self.assertEqual((s, h.get("retry-after")), (429, "30"))
        self.env.settings.trigger_rate_limit_per_minute = 20


class ApprovalApiTests(ApiBase):
    def test_full_approval_flow_over_http_with_role_and_sod_enforcement(self):
        rid = self.env.repo("payments-service")["id"]
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", {"allow_repair": True}, role="operator")
        self.assertEqual(s, 403)  # operators cannot request write-capable work
        s, b, _ = self.call("POST", f"/api/repos/{rid}/trigger", {"allow_repair": True}, role="admin", headers={"Idempotency-Key": "repair-key-0001-ab"})
        self.assertEqual(s, 201)
        jid = b["job"]["id"]
        self.env.run()
        s, d, _ = self.call("GET", f"/api/jobs/{jid}", role="approver")
        self.assertEqual(d["job"]["state"], "WAITING_FOR_APPROVAL")
        aid = next(a["id"] for a in d["approvals"] if a["status"] == "pending")
        self.assertIn("not UNWIND", d["approvals"][0]["provider_label"])
        acts = {a["action"]: a for a in d["actions"]}
        self.assertTrue(acts["approve"]["enabled"])
        _, dadmin, _ = self.call("GET", f"/api/jobs/{jid}", role="admin")
        self.assertIn("separation of duties", {a["action"]: a for a in dadmin["actions"]}["approve"]["reason"])
        s, r, _ = self.call("POST", f"/api/approvals/{aid}/approve", {"note": "ok"}, role="admin")
        self.assertEqual((s, r["error"]["code"]), (403, "SEPARATION_OF_DUTIES"))
        s, r, _ = self.call("POST", f"/api/approvals/{aid}/approve", {"note": "ok"}, role="operator")
        self.assertEqual(s, 403)
        s, r, _ = self.call("POST", f"/api/approvals/{aid}/approve", {"note": "reviewed diff"}, role="approver")
        self.assertEqual((s, r["status"]), (200, "approved"))
        self.env.drain()
        s, d, _ = self.call("GET", f"/api/jobs/{jid}", role="viewer")
        self.assertEqual(d["job"]["outcome"], "repair_verified")
        kinds = {a["kind"]: a["id"] for a in d["artifacts"]}
        s, art, _ = self.call("GET", f"/api/jobs/{jid}/artifacts/{kinds['repair_proof']}", role="viewer")
        self.assertEqual(s, 200)
        self.assertEqual(json.loads(art["content"])["verifier"]["verdict"], "agree")
        s, art2, _ = self.call("GET", f"/api/jobs/job_other/artifacts/{kinds['repair_proof']}", role="viewer")
        self.assertEqual(s, 404)  # artifacts are only reachable through their own job


class ScheduleApiTests(ApiBase):
    def body(self, **kw):
        b = {"name": "api-nightly", "repo_id": self.env.repo("legacy-batch")["id"], "kind": "recurring", "timezone": "Asia/Kolkata",
             "recurrence": {"type": "daily", "at": "02:00"}}
        b.update(kw)
        return b

    def test_validate_preview_create_update_pause_resume_disable_delete(self):
        s, v, _ = self.call("POST", "/api/schedules/validate", self.body(), role="operator")
        self.assertEqual(s, 200)
        self.assertEqual(len(v["next_runs"]), 5)
        self.assertIn("Asia/Kolkata", v["recurrence_text"])
        self.assertEqual(v["warnings"], [])
        s, v2, _ = self.call("POST", "/api/schedules/validate", self.body(repo_id=self.env.repo("payments-service")["id"], allow_repair=True), role="admin")
        self.assertTrue(v2["write_capable"] and v2["warnings"])
        self.assertEqual(self.call("POST", "/api/schedules/validate", self.body(timezone="Mars/Base"), role="operator")[1]["error"]["code"], "INVALID_TIMEZONE")
        s, c, _ = self.call("POST", "/api/schedules", self.body(), role="operator")
        self.assertEqual(s, 201)
        sid = c["id"]
        self.assertEqual(self.call("POST", "/api/schedules", self.body(), role="operator")[0], 409)  # duplicate name
        self.assertEqual(self.call("POST", "/api/schedules", self.body(name="rw", repo_id=self.env.repo("payments-service")["id"], allow_repair=True), role="operator")[0], 403)
        s, u, _ = self.call("PATCH", f"/api/schedules/{sid}", {"recurrence": {"type": "daily", "at": "03:15"}}, role="operator")
        self.assertEqual((s, u["recurrence"]["at"]), (200, "03:15"))
        for action, status in (("pause", "paused"), ("resume", "active"), ("disable", "disabled"), ("enable", "active")):
            s, r, _ = self.call("POST", f"/api/schedules/{sid}/{action}", {}, role="operator")
            self.assertEqual((s, r["status"]), (200, status))
        self.assertEqual(self.call("POST", f"/api/schedules/{sid}/explode", {}, role="operator")[0], 400)
        s, g, _ = self.call("GET", f"/api/schedules/{sid}", role="viewer")
        self.assertIn("runs", g)
        self.assertEqual(self.call("DELETE", f"/api/schedules/{sid}", role="operator")[0], 204)
        self.assertEqual(self.call("GET", f"/api/schedules/{sid}", role="viewer")[0], 404)


class ReadModelTests(ApiBase):
    def test_every_console_read_model_responds_and_is_secret_free(self):
        rid = self.env.repo("payments-service")["id"]
        self.call("POST", f"/api/repos/{rid}/trigger", {}, role="operator", headers={"Idempotency-Key": "rm-key-0001-abcdef"})
        self.env.drain()
        blob = ""
        for path in ("/api/overview", "/api/fleet", "/api/repos", "/api/findings", "/api/recovery", "/api/audit", "/api/audit/extras",
                     "/api/settings", "/api/metrics", "/api/schedules", "/api/jobs"):
            s, b, _ = self.call("GET", path, role="viewer")
            self.assertEqual(s, 200, path)
            blob += json.dumps(b)
        for secret in TOK.values():
            self.assertNotIn(secret, blob)
        s, b, _ = self.call("GET", "/api/audit", role="viewer")
        self.assertTrue(b["chain"]["ok"])
        s, f, _ = self.call("GET", f"/api/findings?repo_id={rid}&severity=HIGH", role="viewer")
        self.assertTrue(f["items"])
        s, fd, _ = self.call("GET", f"/api/findings/{f['items'][0]['id']}", role="viewer")
        self.assertTrue({"finding", "evidence", "facts", "hypotheses", "repair_plan", "observations"} <= set(fd))
        s, a, _ = self.call("GET", "/api/audit?type=job.transition&limit=5", role="viewer")
        self.assertTrue(all(i["type"] == "job.transition" for i in a["items"]))

    def test_overview_modes_and_honest_integration_status(self):
        s, o, _ = self.call("GET", "/api/overview", role="viewer")
        self.assertEqual(o["mode"]["execution"], "local")
        self.assertEqual(o["mode"]["aws"]["status"], "not_configured")
        s, st, _ = self.call("GET", "/api/settings", role="viewer")
        comp = {c["id"]: c["status"] for c in st["components"]}
        self.assertEqual((comp["github"], comp["tavily"], comp["model"], comp["aws"], comp["governance"]),
                         ("not_implemented", "not_implemented", "not_implemented", "not_configured", "stub"))
        s, fl, _ = self.call("GET", "/api/fleet", role="viewer")
        self.assertTrue(all(r["github"]["status"] == "not_connected" for r in fl["items"]))

    def test_watchdog_and_scheduler_ticks_are_admin_only(self):
        self.assertEqual(self.call("POST", "/api/watchdog/tick", {}, role="operator")[0], 403)
        s, b, _ = self.call("POST", "/api/watchdog/tick", {}, role="admin")
        self.assertEqual(s, 200)
        self.assertIn("alerts_open", b)

    def test_provider_check_is_a_real_check(self):
        s, b, _ = self.call("POST", "/api/providers/local-advisories/check", {}, role="operator")
        self.assertEqual((s, b["ok"]), (200, True))
        self.assertEqual(self.call("POST", "/api/providers/nope/check", {}, role="operator")[0], 404)


class WebhookApiTests(unittest.TestCase):
    def test_webhook_route_requires_signature_and_dedupes(self):
        import hashlib, hmac
        env = Env(env={"NIGHTSHIFT_WEBHOOK_SECRET": "api-webhook-secret-not-real"})
        srv = create_server(env.app, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            body = json.dumps({"repository": {"full_name": "demo/legacy-batch"}}).encode()
            sig = "sha256=" + hmac.new(b"api-webhook-secret-not-real", body, hashlib.sha256).hexdigest()

            def post(sig_, delivery):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                c.request("POST", "/api/webhooks/github", body=body, headers={"X-Hub-Signature-256": sig_, "X-GitHub-Delivery": delivery, "X-GitHub-Event": "push"})
                r = c.getresponse()
                return r.status, json.loads(r.read())
            self.assertEqual(post("sha256=bad", "api-deliv-0001")[0], 401)
            s1, b1 = post(sig, "api-deliv-0001")
            s2, b2 = post(sig, "api-deliv-0001")
            self.assertEqual((s1, s2, b2["duplicate"], b1["job_id"] == b2["job_id"]), (202, 200, True, True))
        finally:
            srv.shutdown()
            srv.server_close()
            env.close()


if __name__ == "__main__":
    unittest.main()
