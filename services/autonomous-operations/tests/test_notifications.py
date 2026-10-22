import hashlib, hmac, json
from helpers import *
from aegisnova_ops import providers as P
from aegisnova_ops.providers import SnsProvider, WhatsAppCloudProvider, classify_aws_exception
from aegisnova_ops.engine import Refused
from aegisnova_ops.util import redact


class ClientError(Exception):
    def __init__(self, code): self.response = {"Error": {"Code": code}}


class FakeSns:
    def __init__(self, exc=None): self.calls, self.exc = [], exc
    def publish(self, **kw):
        self.calls.append(kw)
        if self.exc: raise self.exc
        return {"MessageId": "sns-123"}


SNS_ENV = {"AEGIS_AWS_ENABLED": "true", "AWS_REGION": "eu-west-1", "SNS_EMAIL_TOPIC_ARN": "arn:aws:sns:eu-west-1:111122223333:t",
           "SNS_SMS_ENABLED": "true", "AEGIS_RECIPIENT_ALLOWLIST": "a@example.com,+15555550100", "AEGIS_ENABLE_REAL_SEND": "true"}
WA_ENV = {"WHATSAPP_ACCESS_TOKEN": "tok", "WHATSAPP_PHONE_NUMBER_ID": "123", "WHATSAPP_APP_SECRET": "appsecret",
          "WHATSAPP_WEBHOOK_VERIFY_TOKEN": "vt", "WHATSAPP_TEMPLATE_NAME": "ops_alert", "WHATSAPP_RECIPIENT_ALLOWLIST": "+15555550100",
          "AEGIS_ENABLE_REAL_SEND": "true"}


def notif(app, channel="email", dest="x@local.test", mode="SIMULATED", **kw):
    n = app.e.create_notification(channel, dest, mode, "test", **kw)
    return n


class SnsTests(unittest.TestCase):
    def test_publish_success_records_acceptance_not_delivery(self):
        c = FakeSns(); app, _ = make(env=SNS_ENV, sns_client=c)
        app.e.set_consent("sms", "+15555550100", "opted_in", "t")
        n = app.e.create_notification("sms", "+15555550100", "REAL", "test", confirmed_real=True)
        app.e.deliver_notifications()
        row = app.s.one("SELECT * FROM notifications WHERE id=?", (n["id"],))
        self.assertEqual((row["status"], row["provider_message_id"], row["delivery_verified"]), ("ACCEPTED", "sns-123", 0))
        self.assertEqual(c.calls[0]["PhoneNumber"], "+15555550100")

    def test_email_publish_uses_topic_and_allowlist(self):
        c = FakeSns(); app, _ = make(env=SNS_ENV, sns_client=c)
        app.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=True)
        app.e.create_notification("email", "evil@example.com", "REAL", "test", confirmed_real=True)
        app.e.deliver_notifications()
        self.assertEqual(len(c.calls), 1); self.assertIn("TopicArn", c.calls[0])
        self.assertEqual(app.s.one("SELECT status, error_class FROM notifications WHERE destination='evil@example.com'")["error_class"], "policy")

    def test_error_classification(self):
        self.assertEqual(classify_aws_exception(ClientError("Throttling"))[0], P.TRANSIENT)
        self.assertEqual(classify_aws_exception(ClientError("InvalidParameter"))[0], P.PERMANENT)
        self.assertEqual(classify_aws_exception(ClientError("OptedOut"))[0], P.PERMANENT)
        class ReadTimeoutError(Exception): pass
        class EndpointConnectionError(Exception): pass
        self.assertEqual(classify_aws_exception(ReadTimeoutError())[0], P.AMBIGUOUS)
        self.assertEqual(classify_aws_exception(EndpointConnectionError())[0], P.TRANSIENT)

    def test_permanent_error_not_retried(self):
        c = FakeSns(ClientError("InvalidParameter")); app, _ = make(env=SNS_ENV, sns_client=c)
        n = app.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=True)
        app.e.deliver_notifications(); app.e.deliver_notifications()
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "FAILED"); self.assertEqual(len(c.calls), 1)

    def test_transient_retries_then_dead_letters(self):
        c = FakeSns(ClientError("Throttling")); app, clock = make(env=SNS_ENV, sns_client=c)
        app.e.cfg.breaker_threshold = 99
        app.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=True)
        for _ in range(8):
            app.e.deliver_notifications(); clock.advance(100)
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "DEAD_LETTERED")
        self.assertEqual(len(c.calls), app.e.cfg.notif_max_attempts)
        self.assertEqual(app.s.one("SELECT COUNT(*) c FROM dead_letters WHERE kind='notification'")["c"], 1)

    def test_ambiguous_timeout_is_unknown_not_delivered_and_not_resent(self):
        class ReadTimeoutError(Exception): pass
        c = FakeSns(ReadTimeoutError()); app, clock = make(env=SNS_ENV, sns_client=c)
        app.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=True)
        app.e.deliver_notifications(); clock.advance(500); app.e.deliver_notifications()
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "UNKNOWN"); self.assertEqual(len(c.calls), 1)

    def test_no_network_without_configuration_or_confirmation(self):
        c = FakeSns()
        app, _ = make(env={}, sns_client=c)       # unconfigured
        app.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "FAILED"); self.assertEqual(c.calls, [])
        app2, _ = make(env=SNS_ENV, sns_client=c)  # configured but NOT confirmed
        app2.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=False); app2.e.deliver_notifications()
        self.assertEqual(app2.s.one("SELECT suppress_reason FROM notifications")["suppress_reason"], "real_send_not_confirmed"); self.assertEqual(c.calls, [])

    def test_api_real_send_requires_flag_confirmation_and_admin(self):
        c = FakeSns(); app, _ = make(env=SNS_ENV, sns_client=c)
        body = {"channel": "email", "destination": "a@example.com", "confirm": "SEND", "confirm_destination": "a@example.com"}
        self.assertEqual(call(app, "POST", "/api/notifications/send-real", "operator", body)[0], 403)
        self.assertEqual(call(app, "POST", "/api/notifications/send-real", "admin", dict(body, confirm="yes"))[0], 400)
        self.assertEqual(call(app, "POST", "/api/notifications/send-real", "admin", dict(body, confirm_destination="b@example.com"))[0], 400)
        self.assertEqual(c.calls, [])
        st, _ = call(app, "POST", "/api/notifications/send-real", "admin", body); self.assertEqual(st, 202)
        app.e.deliver_notifications(); self.assertEqual(len(c.calls), 1)
        app3, _ = make(env={k: v for k, v in SNS_ENV.items() if k != "AEGIS_ENABLE_REAL_SEND"}, sns_client=c)
        self.assertEqual(call(app3, "POST", "/api/notifications/send-real", "admin", body)[1]["error"]["code"], "real_send_disabled")

    def test_destination_validation(self):
        p = SnsProvider(SNS_ENV)
        self.assertIsNotNone(p.validate_destination("sms", "12345")); self.assertIsNotNone(p.validate_destination("email", "nope"))
        self.assertIsNotNone(p.validate_destination("whatsapp", "+15555550100"))
        self.assertIsNone(p.validate_destination("sms", "+15555550100"))

    def test_sns_never_handles_whatsapp(self):
        self.assertNotIn("whatsapp", SnsProvider.channels)


class FakeHttp:
    def __init__(self, status=200, data=None, exc=None): self.calls, self.status, self.data, self.exc = [], status, data, exc
    def __call__(self, method, url, headers, body, timeout=10):
        self.calls.append((method, url, body))
        if self.exc: raise self.exc
        return self.status, self.data if self.data is not None else {"messages": [{"id": "wamid.1"}]}


def sign(raw): return "sha256=" + hmac.new(b"appsecret", raw, hashlib.sha256).hexdigest()


class WhatsAppTests(unittest.TestCase):
    def mk(self, http=None):
        app, clock = make(env=WA_ENV, wa_http=http or FakeHttp())
        app.e.set_consent("whatsapp", "+15555550100", "opted_in", "t")
        return app, clock

    def test_adapter_uses_fixed_official_endpoint_and_template(self):
        h = FakeHttp(); app, _ = self.mk(h)
        app.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()
        m, url, body = h.calls[0]
        self.assertTrue(url.startswith("https://graph.facebook.com/") and url.endswith("/123/messages"))
        self.assertEqual(body["type"], "template"); self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "ACCEPTED")

    def test_consent_required_and_opt_out_suppresses(self):
        h = FakeHttp(); app, _ = make(env=WA_ENV, wa_http=h)
        app.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True)
        self.assertEqual(app.s.one("SELECT suppress_reason FROM notifications")["suppress_reason"], "no_recorded_consent")
        app2, _ = self.mk(h)
        n = app2.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True)
        app2.e.set_consent("whatsapp", "+15555550100", "opted_out", "t"); app2.e.deliver_notifications()
        self.assertEqual(app2.s.one("SELECT status, suppress_reason FROM notifications WHERE id=?", (n["id"],))["suppress_reason"], "opted_out")
        self.assertEqual(h.calls, [])

    def test_http_errors_retryable_vs_permanent(self):
        app, _ = self.mk(FakeHttp(429, {"error": {"code": 130429}}))
        app.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "RETRYING")
        app2, _ = self.mk(FakeHttp(400, {"error": {"code": 131026}}))
        app2.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True); app2.e.deliver_notifications()
        self.assertEqual(app2.s.one("SELECT status FROM notifications")["status"], "FAILED")

    def test_timeout_is_unknown(self):
        app, _ = self.mk(FakeHttp(exc=TimeoutError()))
        app.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "UNKNOWN")

    def test_unconfigured_whatsapp_fails_without_network(self):
        h = FakeHttp(); app, _ = make(env={"AEGIS_ENABLE_REAL_SEND": "true"}, wa_http=h)
        app.e.set_consent("whatsapp", "+15555550100", "opted_in", "t")
        app.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()
        self.assertEqual(h.calls, []); self.assertEqual(app.s.one("SELECT error_class FROM notifications")["error_class"], "unconfigured")

    def _accepted(self, app):
        app.e.create_notification("whatsapp", "+15555550100", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()

    def _hook(self, app, status, ts="1", mid="wamid.1", sig=None):
        raw = json.dumps({"entry": [{"changes": [{"value": {"statuses": [{"id": mid, "status": status, "timestamp": ts}]}}]}]}).encode()
        return call(app, "POST", "/api/webhooks/whatsapp", None, raw=raw, headers={"x-hub-signature-256": sig or sign(raw), "content-type": "application/json"})

    def test_webhook_signature_required(self):
        app, _ = self.mk(); self._accepted(app)
        self.assertEqual(self._hook(app, "delivered", sig="sha256=bad")[0], 401)
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "ACCEPTED")
        self.assertEqual(self._hook(app, "delivered")[0], 200)
        n = app.s.one("SELECT * FROM notifications"); self.assertEqual((n["status"], n["delivery_verified"]), ("DELIVERED", 1))

    def test_duplicate_and_out_of_order_receipts(self):
        app, _ = self.mk(); self._accepted(app)
        self._hook(app, "delivered", "2")
        self.assertEqual(self._hook(app, "delivered", "2")[1]["results"], ["duplicate"])
        self.assertEqual(self._hook(app, "sent", "1")[1]["results"], ["out_of_order_ignored"])
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "DELIVERED")
        self._hook(app, "read", "3"); self.assertEqual(app.s.one("SELECT receipt_state FROM notifications")["receipt_state"], "READ")

    def test_unmatched_receipt_recorded_then_applied_when_message_known(self):
        app, _ = self.mk()
        self.assertEqual(self._hook(app, "delivered")[1]["results"], ["unmatched"])
        self._accepted(app)     # message id becomes known afterwards
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "DELIVERED")

    def test_failed_receipt_marks_failed(self):
        app, _ = self.mk(); self._accepted(app); self._hook(app, "failed")
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "FAILED")

    def test_verify_challenge(self):
        app, _ = self.mk()
        st, out = call(app, "GET", "/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=abc", None)
        self.assertEqual((st, out), (200, "abc"))
        self.assertEqual(call(app, "GET", "/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=no&hub.challenge=abc", None)[0], 403)

    def test_webhook_503_when_unconfigured(self):
        app, _ = make(); self.assertEqual(call(app, "POST", "/api/webhooks/whatsapp", None, raw=b"{}")[0], 503)


class LocalAndSimulatorTests(Base):
    def test_simulator_behaviours(self):
        ok = notif(self.app, dest="ok@local.test"); perm = notif(self.app, dest="fail-permanent@local.test")
        amb = notif(self.app, dest="ambiguous@local.test"); flaky = notif(self.app, dest="flaky-2@local.test")
        self.e.deliver_notifications()
        st = lambda n: self.s.one("SELECT status FROM notifications WHERE id=?", (n["id"],))["status"]
        self.assertEqual([st(ok), st(perm), st(amb), st(flaky)], ["ACCEPTED", "FAILED", "UNKNOWN", "RETRYING"])
        for _ in range(3): self.clock.advance(100); self.e.deliver_notifications()
        self.assertEqual(st(flaky), "ACCEPTED")

    def test_delivered_only_via_receipt_and_marked_unverified(self):
        n = notif(self.app, dest="ok@local.test"); self.e.deliver_notifications()
        row = self.s.one("SELECT * FROM notifications")
        self.assertNotEqual(row["status"], "DELIVERED")
        self.e.apply_receipt("simulator", row["provider_message_id"], "e1", "delivered", None, False, "simulator")
        row = self.s.one("SELECT * FROM notifications"); self.assertEqual((row["status"], row["delivery_verified"]), ("DELIVERED", 0))

    def test_unverified_receipt_for_real_notification_rejected(self):
        app, _ = make(env=SNS_ENV, sns_client=FakeSns())
        app.e.create_notification("email", "a@example.com", "REAL", "test", confirmed_real=True); app.e.deliver_notifications()
        self.assertEqual(app.e.apply_receipt("aws-sns", "sns-123", "e1", "delivered", None, False, "x"), "rejected_unverified")
        self.assertEqual(app.s.one("SELECT status FROM notifications")["status"], "ACCEPTED")

    def test_idempotent_creation(self):
        a = notif(self.app, idem="same"); b = notif(self.app, idem="same")
        self.assertEqual(a["id"], b["id"])

    def test_storm_suppression(self):
        for i in range(self.e.cfg.storm_limit + 2): notif(self.app, dest="s@local.test", idem=f"i{i}")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notifications WHERE suppress_reason='storm_suppression'")["c"], 2)

    def test_circuit_breaker_opens_and_defers(self):
        for i in range(5): notif(self.app, dest=f"fail-transient{i}@local.test")
        self.e.deliver_notifications()
        h = self.s.one("SELECT * FROM provider_health"); self.assertEqual(h["state"], "OPEN")
        before = self.s.one("SELECT COUNT(*) c FROM notification_attempts")["c"]
        self.e.deliver_notifications()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notification_attempts")["c"], before)

    def test_rate_limit_defers_not_fails(self):
        self.e.cfg.notify_rate_per_min = 2
        for i in range(4): notif(self.app, dest=f"r{i}@local.test", idem=f"r{i}")
        self.e.deliver_notifications()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notifications WHERE status='ACCEPTED'")["c"], 2)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notifications WHERE status='CREATED'")["c"], 2)

    def test_replay_unknown_creates_new_attempt_and_keeps_history(self):
        n = notif(self.app, dest="ambiguous@local.test"); self.e.deliver_notifications()
        with self.assertRaises(Refused): self.e.replay_notification(n["id"], "a", confirm=False)
        self.e.replay_notification(n["id"], "admin-1", confirm=True); self.e.deliver_notifications()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notification_attempts")["c"], 2)
        self.assertTrue(self.s.one("SELECT 1 FROM events WHERE type='audit.notification.replay'"))

    def test_notification_dlq_redrive(self):
        n = notif(self.app, dest="fail-transient@local.test"); self.e.cfg.breaker_threshold = 99
        for _ in range(8): self.e.deliver_notifications(); self.clock.advance(100)
        d = self.s.one("SELECT * FROM dead_letters WHERE kind='notification'")
        self.e.redrive([d["id"]], "a", dry_run=False, confirm=True)
        self.assertEqual(self.s.one("SELECT status FROM notifications")["status"], "QUEUED")

    def test_retention_scrubs_destination(self):
        n = notif(self.app, dest="ok@local.test"); self.e.deliver_notifications()
        self.clock.advance(86400 * 40)
        self.assertEqual(self.e.purge_expired()["destinations_scrubbed"], 1)
        self.assertIsNone(self.s.one("SELECT destination FROM notifications")["destination"])

    def test_workflow_cannot_request_real_mode(self):
        from aegisnova_ops.contracts import ValidationError
        with self.assertRaises(ValidationError):
            self.e.start_run({"workflow_type": "sample.governed_action", "payload": {"notify": {"channel": "email", "destination": "a@b.co", "mode": "REAL"}}})


class RedactionTests(unittest.TestCase):
    def test_redact(self):
        s = redact("fail for bob@example.com +15555550100 Bearer abc.def token=SECRET123 AKIAABCDEFGHIJKLMNOP " + "A" * 50)
        for leak in ("bob@example.com", "15555550100", "abc.def", "SECRET123", "AKIAABCDEFGHIJKLMNOP", "A" * 50):
            self.assertNotIn(leak, s)

    def test_api_outputs_mask_destination_and_errors(self):
        app, _ = make(); n = notif(app, dest="fail-permanent@local.test"); app.e.deliver_notifications()
        st, out = call(app, "GET", "/api/notifications", "viewer"); txt = json.dumps(out)
        self.assertNotIn("fail-permanent@local.test", txt); self.assertIn("f***@local.test", txt)
        self.assertNotIn("destination\"", txt)
