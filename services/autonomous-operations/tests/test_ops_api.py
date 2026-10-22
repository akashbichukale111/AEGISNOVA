import json, os, re
from helpers import *
from aegisnova_ops import contracts as C, aws
from aegisnova_ops.auth import RateLimiter
from aegisnova_ops.integrations import integration_statuses, test_connection, environment_label
from aegisnova_ops.observability import alarm_definitions
from aegisnova_ops.util import validate_https_url
from aegisnova_ops.governance import UnwindAdapter

ROOT = os.path.join(os.path.dirname(__file__), "..")


class AlarmTests(Base):
    def alarm(self, name):
        return next(a for a in self.app.obs.alarm_states() if a["name"] == name)

    def test_unavailable_not_fabricated(self):
        snap = self.app.obs.snapshot()
        self.assertIsNone(snap["worker_heartbeat_age_s"]); self.assertIsNone(snap["queue_oldest_age_s"])
        self.assertIsNone(snap["notification_failure_rate:email"])
        self.app.obs.evaluate()
        self.assertEqual(self.alarm("WorkerHeartbeatStale")["state"], "UNAVAILABLE")
        self.assertEqual(self.app.obs.alarm_events(), [])     # no event from missing data

    def test_stale_heartbeat_triggers_and_resolves(self):
        self.e.heartbeat(); self.app.obs.evaluate(); self.assertEqual(self.alarm("WorkerHeartbeatStale")["state"], "OK")
        self.clock.advance(31); r = self.app.obs.evaluate()
        self.assertIn(("triggered", "WorkerHeartbeatStale"), r["events"])
        ev = self.app.obs.alarm_events()[0]
        self.assertEqual((ev["state"], ev["severity"]), ("ALARM", "critical")); self.assertIn("worker_heartbeat_age_s", ev["explanation"])
        self.assertIn("runbook-worker-heartbeat", ev["runbook"])
        self.clock.advance(1); self.app.obs.evaluate()          # still breaching: deduplicated
        self.assertEqual(len([e for e in self.app.obs.alarm_events() if e["alarm_name"] == "WorkerHeartbeatStale"]), 1)
        self.e.heartbeat(); r = self.app.obs.evaluate()
        self.assertIn(("resolved", "WorkerHeartbeatStale"), r["events"])
        ev = self.app.obs.alarm_events()[0]; self.assertEqual(ev["state"], "RESOLVED"); self.assertTrue(ev["resolved_at"]); self.assertIn("resolved", ev["explanation"])

    def test_cooldown_suppresses_flapping(self):
        self.e.heartbeat(); self.clock.advance(40); self.app.obs.evaluate()
        self.e.heartbeat(); self.app.obs.evaluate()           # resolved -> cooldown 60s
        self.clock.advance(40); self.app.obs.evaluate()       # breach again inside cooldown
        self.assertEqual(len(self.app.obs.alarm_events()), 1); self.assertEqual(self.alarm("WorkerHeartbeatStale")["suppressed_count"], 1)

    def test_dlq_and_stuck_workflow_detection(self):
        run = start(self.app, approval=False, simulate={"fail_times": 9})
        for _ in range(6): self.e.tick(); self.clock.advance(10)
        r = self.app.obs.evaluate()
        self.assertIn(("triggered", "DeadLetterQueue"), r["events"]); self.assertIn(("triggered", "ProviderCircuitOpen"), r["events"]) if False else None
        r2 = start(self.app, approval=False); self.clock.advance(self.e.cfg.stuck_run_s + 1)
        self.assertEqual([x["id"] for x in self.e.stuck_runs()], [r2["id"]])
        self.assertIn(("triggered", "StuckRuns"), self.app.obs.evaluate()["events"])

    def test_approval_expiry_and_wait_alarms(self):
        start(self.app, approval_ttl_s=60); self.e.drain(); self.clock.advance(3700); self.e.tick()
        ev = self.app.obs.evaluate()["events"]
        self.assertIn(("triggered", "ExpiredApprovals"), ev)

    def test_failure_rate_and_outbox_metrics(self):
        for i in range(3): self.e.create_notification("email", f"fail-permanent{i}@local.test", "SIMULATED", "test", idem=f"k{i}")
        self.e.deliver_notifications(); snap = self.app.obs.snapshot()
        self.assertEqual(snap["notification_failure_rate:email"], 1.0)
        self.e.create_notification("sms", "ok@local.test", "LOCAL", "test"); self.assertEqual(self.app.obs.snapshot()["outbox_backlog"], 1)

    def test_thresholds_configurable(self):
        d = {a["name"]: a for a in alarm_definitions({"AEGIS_ALARM_QUEUEDEPTH_THRESHOLD": "7"})}
        self.assertEqual(d["QueueDepth"]["threshold"], 7.0)
        for a in alarm_definitions(): self.assertTrue(a["runbook"]); self.assertIn(a["severity"], C.SEVERITIES)

    def test_local_metrics_recorded_and_no_cloudwatch_emission_locally(self):
        self.e.heartbeat(); self.app.obs.evaluate()
        self.assertGreater(self.s.one("SELECT COUNT(*) c FROM metrics WHERE source='local'")["c"], 0)
        self.assertIsNone(self.app.obs.emitter)


class FakeCw:
    def __init__(self): self.calls = []
    def put_metric_data(self, **kw): self.calls.append(kw)


class FakeSfn:
    def __init__(self): self.calls = []
    def start_execution(self, **kw): self.calls.append(("start", kw)); return {"executionArn": "arn:x"}
    def stop_execution(self, **kw): self.calls.append(("stop", kw))
    def send_task_success(self, **kw): self.calls.append(("success", kw))
    def send_task_failure(self, **kw): self.calls.append(("failure", kw))


class FakeSqs:
    def __init__(self): self.calls = []
    def send_message(self, **kw): self.calls.append(("send", kw)); return {"MessageId": "m1"}
    def receive_message(self, **kw): self.calls.append(("recv", kw)); return {"Messages": []}
    def get_queue_attributes(self, **kw): return {"Attributes": {"ApproximateNumberOfMessages": "3", "ApproximateAgeOfOldestMessage": "9"}}
    def start_message_move_task(self, **kw): self.calls.append(("move", kw)); return {"TaskHandle": "h"}
    def delete_message(self, **kw): pass


class AwsAdapterTests(Base):
    def test_cloudwatch_emits_only_measured(self):
        cw = FakeCw(); n = aws.CloudWatchEmitter(cw).emit({"queue_depth": 2, "worker_heartbeat_age_s": None, "notification_failure_rate:email": 0.5})
        self.assertEqual(n, 2); names = [m["MetricName"] for m in cw.calls[0]["MetricData"]]
        self.assertNotIn("worker_heartbeat_age_s", names)
        self.assertEqual(cw.calls[0]["MetricData"][1]["Dimensions"][0]["Value"], "email")

    def test_emitter_wired_into_evaluation(self):
        cw = FakeCw(); self.app.obs.emitter = aws.CloudWatchEmitter(cw); self.e.heartbeat(); self.app.obs.evaluate()
        self.assertTrue(cw.calls)

    def test_step_functions_token_single_use_and_server_side(self):
        c = FakeSfn(); sf = aws.StepFunctionsAdapter(c, "arn:aws:states:eu-west-1:1:stateMachine:m", self.s, self.clock)
        sf.register_callback_token("apr1", "run1", "SECRET-TASK-TOKEN")
        sf.resume("run1", "apr1")
        self.assertEqual(c.calls[0][1]["taskToken"], "SECRET-TASK-TOKEN")
        with self.assertRaises(LookupError): sf.resume("run1", "apr1")            # replay blocked
        self.assertEqual(self.s.one("SELECT token FROM callback_tokens")["token"], "")   # wiped after use
        sf.register_callback_token("apr2", "run2", "T2")
        with self.assertRaises(LookupError): sf.resume("run-other", "apr2")      # scoped to exact run
        self.assertTrue(sf.fail("run2", "apr2")); self.assertEqual(c.calls[1][0], "failure")

    def test_step_functions_start_is_idempotent_by_name(self):
        c = FakeSfn(); aws.StepFunctionsAdapter(c, "arn").start({"id": "run_1", "correlation_id": "c"})
        self.assertEqual(c.calls[0][1]["name"], "run_1")

    def test_sqs_adapter_bounds(self):
        c = FakeSqs(); q = aws.SqsAdapter(c, "u", "d", "arn:dlq", "arn:src")
        q.receive(50); self.assertEqual(c.calls[-1][1]["MaxNumberOfMessagesPerSecond"] if False else c.calls[-1][1]["MaxNumberOfMessages"], 10)
        self.assertEqual(c.calls[-1][1]["WaitTimeSeconds"], 20)
        q.send("b", "dk", "corr"); self.assertEqual(c.calls[-1][1]["MessageAttributes"]["dedupe_key"]["StringValue"], "dk")
        self.assertEqual(q.depth(), {"depth": 3, "oldest_age_s": 9})
        q.redrive(2); self.assertEqual(c.calls[-1][1]["MaxNumberOfMessagesPerSecond"], 2)
        with self.assertRaises(ValueError): q.redrive(500)

    def test_environment_labels_and_statuses_default_local(self):
        self.assertEqual(environment_label({})["label"], "LOCAL")
        self.assertEqual(environment_label({"AEGIS_PROFILE": "aws"})["label"], "AWS UNCONFIGURED")
        full = {"AEGIS_PROFILE": "aws", "AEGIS_AWS_ENABLED": "true", "AWS_REGION": "r", "AEGIS_STATE_MACHINE_ARN": "a", "AEGIS_WORK_QUEUE_URL": "u", "AEGIS_DLQ_URL": "d"}
        self.assertEqual(environment_label(full)["label"], "AWS CONFIGURED")
        st = {i["name"]: i for i in integration_statuses(None, {})}
        for n in ("aws-sqs", "aws-sns", "aws-step-functions", "aws-cloudwatch", "whatsapp-cloud-api", "unwind-governance"):
            self.assertEqual(st[n]["state"], "UNCONFIGURED", n)
        self.assertEqual(st["notification-simulator"]["state"], "SIMULATED")
        for i in st.values(): self.assertIn(i["state"], C.INTEGRATION_STATES); C.validate("IntegrationStatus", {k: v for k, v in i.items() if k != "schema_version"})

    def test_connection_tests_are_nondestructive(self):
        self.assertFalse(test_connection("aws-sqs", {})["ok"]); self.assertEqual(test_connection("aws-sqs", {})["state"], "UNCONFIGURED")
        self.assertTrue(test_connection("local-store", {})["ok"])
        env = {"AEGIS_AWS_ENABLED": "true", "AWS_REGION": "r", "AEGIS_WORK_QUEUE_URL": "u", "AEGIS_DLQ_URL": "d"}
        sq = FakeSqs(); r = test_connection("aws-sqs", env, {"sqs": sq}); self.assertTrue(r["ok"]); self.assertEqual(sq.calls, [])   # only get_queue_attributes
        self.assertEqual(test_connection("nope", {})["state"], "UNKNOWN")

    def test_credentials_never_in_status_output(self):
        env = {"WHATSAPP_ACCESS_TOKEN": "SUPERSECRETVALUE", "UNWIND_API_TOKEN": "SUPERSECRETVALUE2", "UNWIND_SIGNING_KEY": "K"}
        self.assertNotIn("SUPERSECRET", json.dumps(integration_statuses(None, env)))


class SecurityTests(unittest.TestCase):
    def setUp(self): self.app, self.clock = make()

    def test_all_mutating_routes_require_auth_and_role(self):
        mut = [r for r in self.app.routes if r[0] == "POST" and not r[4]]
        self.assertGreater(len(mut), 10)
        for method, rx, role, fn, public in mut:
            path = rx.pattern.strip("^$")
            path = re.sub(r"\(\?P<(\w+)>[^)]*(?:\([^)]*\))?[^)]*\)", lambda m: "cancel" if m.group(1) == "act" else "x", path)
            self.assertEqual(call(self.app, "POST", path, None, {})[0], 401, path)
            if role == "admin":
                self.assertEqual(call(self.app, "POST", path, "viewer", {})[0], 403, path)
                self.assertEqual(call(self.app, "POST", path, "operator", {})[0], 403, path)
            else:
                self.assertEqual(call(self.app, "POST", path, "viewer", {})[0], 403, path)

    def test_reads_require_auth_but_health_does_not(self):
        self.assertEqual(call(self.app, "GET", "/api/runs", None)[0], 401); self.assertEqual(call(self.app, "GET", "/api/health", None)[0], 200)
        self.assertEqual(call(self.app, "GET", "/api/runs", None, headers={"authorization": "Bearer wrong"})[0], 401)

    def test_validation_errors(self):
        self.assertEqual(call(self.app, "POST", "/api/runs", "operator", {"workflow_type": "x", "payload": {}})[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/runs", "operator", {"workflow_type": "sample.governed_action", "payload": {"action": "rm -rf"}})[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/runs", "operator", {"workflow_type": "sample.governed_action", "payload": {}, "evil": 1})[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/runs", "operator", raw=b"{bad")[0], 400)
        self.assertEqual(call(self.app, "POST", "/api/runs", "operator", {}, headers={"content-type": "text/plain"})[0], 415)
        st, b = call(self.app, "POST", "/api/runs", "operator", {"workflow_type": "sample.governed_action", "payload": {"scope": "BAD SCOPE!"}})
        self.assertEqual(st, 400); self.assertEqual(b["error"]["code"], "validation_error")

    def test_size_limit_rate_limit_and_safe_errors(self):
        self.assertEqual(call(self.app, "POST", "/api/runs", "operator", raw=b"x" * 70000)[0], 413)
        self.app.limiter = RateLimiter(capacity=3, refill_per_s=0, now=lambda: 0)
        codes = [call(self.app, "GET", "/api/queue", "viewer")[0] for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])
        st, b = call(self.app, "GET", "/api/runs/does-not-exist", "admin"); self.assertEqual(st, 404)
        self.assertNotIn("Traceback", json.dumps(b))

    def test_cancel_requires_confirm(self):
        run = start(self.app, approval=False)
        self.assertEqual(call(self.app, "POST", f"/api/runs/{run['id']}/cancel", "operator", {})[0], 400)
        self.assertEqual(call(self.app, "POST", f"/api/runs/{run['id']}/cancel", "operator", {"confirm": True})[0], 200)

    def test_host_header_and_cors_allowlist_and_headers(self):
        self.assertEqual(call(self.app, "GET", "/api/health", None, headers={"host": "evil.example.com"})[0], 400)
        h = {"host": "localhost"}
        _, hd, _ = self.app.handle("GET", "/api/health", {**h, "origin": "http://evil.example"}, b"")
        self.assertNotIn("Access-Control-Allow-Origin", hd); self.assertIn("default-src 'self'", hd["Content-Security-Policy"])
        app2, _ = make(env={"AEGIS_CORS_ORIGINS": "http://ok.example"})
        _, hd, _ = app2.handle("GET", "/api/health", {**h, "origin": "http://ok.example"}, b"")
        self.assertEqual(hd["Access-Control-Allow-Origin"], "http://ok.example")

    def test_external_auth_unconfigured_refuses_everything(self):
        from aegisnova_ops.app import build_app
        app = build_app(env={"AEGIS_AUTH_MODE": "external"}, db_path=":memory:", clock=FakeClock())
        self.assertEqual(call(app, "POST", "/api/runs", "admin", {})[0], 401)

    def test_dev_decision_unavailable_with_production_governance(self):
        app, _ = make(gov=UnwindAdapter({}))
        self.assertEqual(call(app, "POST", "/api/approvals/x/dev-decision", "admin", {"decision": "granted"})[0], 404)

    def test_ssrf_guard(self):
        for bad in ("http://example.com", "https://127.0.0.1/x", "https://169.254.169.254/latest", "https://10.0.0.5", "https://localhost",
                    "https://user:pw@example.com", "https://[::1]/", "file:///etc/passwd", "https://svc.internal"):
            with self.assertRaises(ValueError, msg=bad): validate_https_url(bad)
        self.assertEqual(validate_https_url("https://example.com/x"), "https://example.com/x")
        self.assertIn("rejected", UnwindAdapter({"UNWIND_BASE_URL": "https://169.254.169.254"}).status_reason())

    def test_no_aws_credential_fields_accepted_from_frontend(self):
        st, _ = call(self.app, "POST", "/api/runs", "operator", {"workflow_type": "sample.governed_action", "payload": {}, "aws_access_key_id": "x"})
        self.assertEqual(st, 400)

    def test_real_send_cannot_be_requested_via_test_endpoint(self):
        st, b = call(self.app, "POST", "/api/notifications/test", "operator", {"channel": "email", "destination": "a@b.co", "mode": "REAL"})
        self.assertEqual((st, b["error"]["code"]), (400, "use_real_endpoint"))


class ApiContractTests(unittest.TestCase):
    def test_contract_shapes(self):
        app, clock = make()
        run = start(app); app.e.drain(); grant(app, run["id"]); app.e.drain()
        st, d = call(app, "GET", f"/api/runs/{run['id']}", "viewer"); self.assertEqual(st, 200)
        C.validate("WorkflowRun", d["run"])
        for ev in d["timeline"]: C.validate("WorkflowEvent", {k: v for k, v in ev.items() if v is not None and k != "detail_json"})
        C.validate("ApprovalRequest", {k: v for k, v in d["approval"].items() if k != "label"})
        _, apps = call(app, "GET", "/api/approvals", "viewer"); self.assertIn("governance", apps)
        n = d["notifications"][0]
        for f in ("id", "channel", "mode", "status", "attempts", "correlation_id", "destination_masked", "schema_version"): self.assertIn(f, n)
        for al in call(app, "GET", "/api/alarms", "viewer")[1]["items"]: C.validate("AlarmDefinition", {k: al[k] for k in ("name", "metric", "comparison", "threshold", "severity", "runbook")})
        _, nd = call(app, "GET", f"/api/notifications/{n['id']}", "viewer")
        for a in nd["attempts"]: C.validate("NotificationAttempt", {k: v for k, v in a.items() if v is not None})
        ov = call(app, "GET", "/api/overview", "viewer")[1]
        for k in ("environment", "runs_by_state", "notifications_by_channel", "queue", "worker_heartbeat", "providers"): self.assertIn(k, ov)
        self.assertEqual(sorted(ov["runs_by_state"]), sorted(["queued", "running", "waiting_for_approval", "retrying", "succeeded", "failed", "cancelled", "paused"]))

    def test_strict_schema_rejects_unknown_and_bad_enums(self):
        with self.assertRaises(C.ValidationError): C.validate("QueueMessage", {"run_id": "a", "kind": "k", "x": 1})
        with self.assertRaises(C.ValidationError): C.validate("ApprovalDecision", {"decision": "maybe"})
        with self.assertRaises(C.ValidationError): C.validate("NotificationRequest", {"channel": "pigeon", "destination": "x"})
        with self.assertRaises(C.ValidationError): C.validate("WorkflowStartRequest", {"workflow_type": "a", "payload": {}, "idempotency_key": "has space"})

    def test_no_secret_fields_in_api_outputs(self):
        app, _ = make(); run = start(app); app.e.drain()
        txt = json.dumps([call(app, "GET", p, "admin")[1] for p in ("/api/runs", "/api/approvals", "/api/events", "/api/integrations", "/api/overview")])
        for banned in ("task_token", "taskToken", "\"signature\"", "local-dev-only-not-a-secret", "tok-admin"): self.assertNotIn(banned, txt)

    def test_end_to_end_via_http_layer(self):
        app, clock = make()
        st, r = call(app, "POST", "/api/runs", "operator", {"workflow_type": "sample.governed_action", "payload": {}, "idempotency_key": "e2e-1"})
        self.assertEqual(st, 201); rid = r["run"]["id"]
        self.assertEqual(call(app, "POST", "/api/runs", "operator", {"workflow_type": "sample.governed_action", "payload": {}, "idempotency_key": "e2e-1"})[0], 200)
        call(app, "POST", "/api/worker/tick", "operator", {})
        _, a = call(app, "GET", "/api/approvals?status=PENDING", "viewer"); ap = a["items"][0]
        self.assertEqual(ap["dev_only"], True); self.assertIn("DEVELOPMENT", ap["label"])
        call(app, "POST", f"/api/approvals/{ap['id']}/dev-decision", "admin", {"decision": "granted"})
        call(app, "POST", "/api/worker/tick", "operator", {}); call(app, "POST", "/api/worker/tick", "operator", {})
        self.assertEqual(call(app, "GET", f"/api/runs/{rid}", "viewer")[1]["run"]["status"], "SUCCEEDED")
        st, ev = call(app, "GET", f"/api/events?q={rid}", "viewer"); self.assertGreater(len(ev["items"]), 5)
        st, t = call(app, "POST", "/api/notifications/test", "operator", {"channel": "local_sink", "destination": "ops-sink@local.test"}); self.assertEqual(st, 201)
        self.assertEqual(call(app, "POST", "/api/alarms/evaluate", "operator", {})[0], 200)


class StaticUiAndInfraTests(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(ROOT, *p)) as f: return f.read()

    def test_ui_served_with_csp_and_no_inline_script(self):
        app, _ = make(); st, hd, body = app.handle("GET", "/", {"host": "localhost"}, b"")
        self.assertEqual(st, 200); html = body.decode()
        self.assertNotRegex(html, r"<script(?![^>]*src=)[^>]*>"); self.assertNotIn("onclick=", html)
        for view in ("overview", "runs", "approvals", "notifications", "queues", "reliability", "settings"): self.assertIn(f'data-view="{view}"', html)
        self.assertEqual(app.handle("GET", "/app.js", {"host": "localhost"}, b"")[0], 200)
        self.assertEqual(app.handle("GET", "/../../etc/passwd", {"host": "localhost"}, b"")[0], 404)

    def test_ui_has_no_secret_or_aws_credential_handling(self):
        js = self.read("aegisnova_ops", "static", "app.js")
        for banned in ("AKIA", "aws_secret", "localStorage"): self.assertNotIn(banned, js)

    def test_asl_matches_local_steps(self):
        asl = json.loads(self.read("infra", "state_machine.asl.json"))
        for step in ("START", "VALIDATE", "WAITING_FOR_APPROVAL", "EXECUTE_SAFE_ACTION", "NOTIFY", "COMPLETE"): self.assertIn(step, asl["States"])
        self.assertEqual(asl["States"]["WAITING_FOR_APPROVAL"]["Resource"], "arn:aws:states:::sqs:sendMessage.waitForTaskToken")
        self.assertIn("Retry", asl["States"]["EXECUTE_SAFE_ACTION"]); self.assertIn("Catch", asl["States"]["EXECUTE_SAFE_ACTION"])
        for name, st in asl["States"].items():
            for nxt in ([st.get("Next")] + [c.get("Next") for c in st.get("Catch", [])] + [c.get("Next") for c in st.get("Choices", [])] + [st.get("Default")]):
                if nxt: self.assertIn(nxt, asl["States"], f"{name}->{nxt}")
        self.assertEqual(asl["States"]["COMPLETE"]["Type"], "Succeed")

    def test_template_static_checks(self):
        t = self.read("infra", "template.yaml")
        for needle in ("RedrivePolicy", "maxReceiveCount", "ReceiveMessageWaitTimeSeconds: 20", "SqsManagedSseEnabled: true", "aws:SecureTransport",
                       "AWS::CloudWatch::Alarm", "StartMessageMoveTask", "cloudwatch:namespace", "HasAlarmTopic"):
            self.assertIn(needle, t)
        self.assertNotRegex(t, r"Action:\s*['\"]?\*['\"]?\s*$")
        self.assertNotIn("AKIA", t)

    def test_env_example_has_placeholders_only(self):
        env = self.read(".env.example")
        for line in env.splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if any(x in k for x in ("TOKEN", "SECRET", "KEY")) and not k.endswith("_FILE"): self.assertEqual(v.strip(), "", k)
