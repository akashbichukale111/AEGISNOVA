import json, os, tempfile
from helpers import *
from aegisnova_ops import statemachine as SM
from aegisnova_ops.contracts import RunStatus as R
from aegisnova_ops.engine import Conflict, Refused
from aegisnova_ops.governance import DecisionRejected, sign_envelope
from aegisnova_ops.store import jdump


class TransitionTests(unittest.TestCase):
    def test_legal(self):
        SM.check_run(R.QUEUED, R.RUNNING); SM.check_run(R.RUNNING, R.WAITING_FOR_APPROVAL)
        SM.check_run(R.RETRY_WAIT, R.RUNNING); SM.check_run(R.FAILED, R.DEAD_LETTERED)

    def test_illegal(self):
        for a, b in [(R.SUCCEEDED, R.RUNNING), (R.CANCELLED, R.QUEUED), (R.WAITING_FOR_APPROVAL, R.SUCCEEDED),
                     (R.QUEUED, R.SUCCEEDED), (R.DEAD_LETTERED, R.RUNNING)]:
            with self.assertRaises(SM.IllegalTransition):
                SM.check_run(a, b)

    def test_engine_rejects_illegal_transition(self):
        app, _ = make()
        run = start(app, approval=False)
        app.e.drain()
        with self.assertRaises(SM.IllegalTransition):
            app.e._transition(run["id"], R.RUNNING)


class SuccessPath(Base):
    def test_full_success_without_approval(self):
        run = start(self.app, approval=False)
        self.e.drain()
        r = self.e.get_run(run["id"])
        self.assertEqual((r["status"], r["step"]), ("SUCCEEDED", "COMPLETE"))
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 1)
        n = self.s.q("SELECT * FROM notifications WHERE run_id=?", (run["id"],))
        self.assertEqual(len(n), 1); self.assertEqual(n[0]["mode"], "LOCAL")
        types = [e["type"] for e in self.e.timeline(run["id"])]
        for t in ("run.created", "run.transition", "step.completed", "notification.created"):
            self.assertIn(t, types)

    def test_timeline_and_notification_attempt_persisted(self):
        run = start(self.app, approval=False); self.e.drain()
        att = self.s.q("SELECT * FROM notification_attempts")
        self.assertEqual(len(att), 1); self.assertEqual(att[0]["outcome"], "ACCEPTED")
        self.assertEqual(self.s.q("SELECT status FROM notifications")[0]["status"], "ACCEPTED")

    def test_events_table_is_append_only(self):
        start(self.app, approval=False)
        import sqlite3
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.x("UPDATE events SET type='x'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.x("DELETE FROM events")

    def test_correlation_id_propagates(self):
        run = start(self.app, approval=False); self.e.drain()
        corr = run["correlation_id"]
        self.assertEqual(self.s.q("SELECT correlation_id c FROM notifications")[0]["c"], corr)
        self.assertEqual(self.s.q("SELECT correlation_id c FROM queue_messages")[0]["c"], corr)


class ApprovalTests(Base):
    def _waiting(self, **kw):
        run = start(self.app, **kw); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "WAITING_FOR_APPROVAL")
        return run

    def test_waits_then_resumes_only_after_valid_decision(self):
        run = self._waiting()
        self.e.drain(); self.assertEqual(status(self.app, run["id"]), "WAITING_FOR_APPROVAL")
        ap, _ = grant(self.app, run["id"]); self.assertEqual(ap["status"], "GRANTED"); self.assertEqual(ap["dev_only"], 1)
        self.e.drain(); self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")

    def test_survives_restart_and_resumes(self):
        d = tempfile.mkdtemp(); db = os.path.join(d, "t.db")
        app, clock = make(db=db)
        run = start(app); app.e.drain()
        app.s.close()
        app2, _ = make(db=db, clock=clock)           # simulated process restart
        app2.e.recover()
        self.assertEqual(status(app2, run["id"]), "WAITING_FOR_APPROVAL")
        app2.e.drain(); self.assertEqual(status(app2, run["id"]), "WAITING_FOR_APPROVAL")
        grant(app2, run["id"]); app2.e.drain()
        self.assertEqual(status(app2, run["id"]), "SUCCEEDED")

    def _tamper(self, run, **changes):
        ap = self.s.one("SELECT * FROM approvals WHERE run_id=?", (run["id"],))
        env = self.app.gov.issue_decision(ap, "granted", self.clock.now())
        env.update(changes)
        env["signature"] = sign_envelope(env, self.app.gov.key)   # validly signed, but wrong binding
        return env

    def test_wrong_scope_run_action_hash_rejected(self):
        run = self._waiting()
        for k, v in (("scope", "other:scope"), ("action", "other"), ("action_hash", "0" * 64), ("run_id", "run_other")):
            with self.assertRaises(DecisionRejected) as cm:
                self.e.submit_decision(self._tamper(run, **{k: v}))
            self.assertEqual(cm.exception.code, "binding_mismatch")
        self.assertEqual(status(self.app, run["id"]), "WAITING_FOR_APPROVAL")

    def test_bad_signature_issuer_audience_rejected(self):
        run = self._waiting()
        ap = self.s.one("SELECT * FROM approvals WHERE run_id=?", (run["id"],))
        env = self.app.gov.issue_decision(ap, "granted", self.clock.now())
        bad = dict(env, signature="0" * 64)
        with self.assertRaises(DecisionRejected) as cm: self.e.submit_decision(bad)
        self.assertEqual(cm.exception.code, "bad_signature")
        for k, code in (("issuer", "bad_issuer"), ("audience", "bad_audience")):
            e2 = dict(env, **{k: "evil"}); e2["signature"] = sign_envelope(e2, self.app.gov.key)
            with self.assertRaises(DecisionRejected) as cm: self.e.submit_decision(e2)
            self.assertEqual(cm.exception.code, code)
        self.assertEqual(status(self.app, run["id"]), "WAITING_FOR_APPROVAL")

    def test_malformed_and_unknown_fields_rejected(self):
        run = self._waiting()
        ap = self.s.one("SELECT * FROM approvals WHERE run_id=?", (run["id"],))
        env = self.app.gov.issue_decision(ap, "granted", self.clock.now())
        with self.assertRaises(DecisionRejected) as cm: self.e.submit_decision(dict(env, extra="x"))
        self.assertEqual(cm.exception.code, "malformed")
        with self.assertRaises(DecisionRejected): self.e.submit_decision({"decision": "granted"})

    def test_expired_decision_and_expired_approval(self):
        run = self._waiting(approval_ttl_s=60)
        ap = self.s.one("SELECT * FROM approvals WHERE run_id=?", (run["id"],))
        env = self.app.gov.issue_decision(ap, "granted", self.clock.now(), ttl_s=30)
        self.clock.advance(61)
        with self.assertRaises(DecisionRejected): self.e.submit_decision(env)
        self.e.tick()
        self.assertEqual(self.s.one("SELECT status FROM approvals")["status"], "EXPIRED")
        self.assertEqual(self.e.get_run(run["id"])["failure_class"], "approval_expired")
        self.assertEqual(status(self.app, run["id"]), "FAILED")

    def test_rejected_decision_does_not_resume(self):
        run = self._waiting(); grant(self.app, run["id"], "rejected"); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "FAILED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 0)

    def test_revoked_before_execution_blocks_run(self):
        run = self._waiting(); grant(self.app, run["id"]); grant_ap = self.s.one("SELECT * FROM approvals")
        env = self.app.gov.issue_decision(grant_ap, "revoked", self.clock.now())
        self.e.submit_decision(env); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "FAILED")
        self.assertEqual(self.e.get_run(run["id"])["failure_class"], "approval_revoked")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 0)

    def test_replayed_event_and_double_grant_resume_once(self):
        run = self._waiting()
        _, env = grant(self.app, run["id"])
        with self.assertRaises(DecisionRejected) as cm: self.e.submit_decision(env)
        self.assertEqual(cm.exception.code, "replayed_event")
        ap = self.s.one("SELECT * FROM approvals")
        env2 = self.app.gov.issue_decision(ap, "granted", self.clock.now())
        with self.assertRaises(DecisionRejected): self.e.submit_decision(env2)   # no longer pending
        self.e.drain()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 1)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM queue_messages WHERE kind='resume'")["c"], 1)

    def test_cross_run_replay_prevented(self):
        r1 = self._waiting(); r2 = start(self.app); self.e.drain()
        ap1 = self.s.one("SELECT * FROM approvals WHERE run_id=?", (r1["id"],))
        env = self.app.gov.issue_decision(ap1, "granted", self.clock.now())
        ap2 = self.s.one("SELECT * FROM approvals WHERE run_id=?", (r2["id"],))
        env["approval_id"] = ap2["id"]; env["signature"] = sign_envelope(env, self.app.gov.key)
        with self.assertRaises(DecisionRejected) as cm: self.e.submit_decision(env)
        self.assertEqual(cm.exception.code, "binding_mismatch")
        self.assertEqual(status(self.app, r2["id"]), "WAITING_FOR_APPROVAL")

    def test_payload_tamper_detected_at_execution(self):
        run = self._waiting(); grant(self.app, run["id"])
        p = json.loads(self.e.get_run(run["id"])["payload_json"]); p["marker"] = "tampered"
        self.s.x("UPDATE workflow_runs SET payload_json=? WHERE id=?", (jdump(p), run["id"]))
        self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "FAILED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 0)

    def test_unconfigured_unwind_stays_waiting_fail_closed(self):
        from aegisnova_ops.governance import UnwindAdapter
        app, clock = make(gov=UnwindAdapter({}))
        run = start(app); app.e.drain()
        ap = app.s.one("SELECT * FROM approvals")
        self.assertEqual(status(app, run["id"]), "WAITING_FOR_APPROVAL")
        self.assertEqual(ap["blocked_reason"], "governance_unconfigured")
        app.e.drain(); self.assertEqual(status(app, run["id"]), "WAITING_FOR_APPROVAL")
        st, _ = call(app, "POST", "/api/governance/callback", role=None, body={"x": 1}); self.assertEqual(st, 503)


class RetryTests(Base):
    def test_transient_failure_retries_with_backoff_then_succeeds(self):
        run = start(self.app, approval=False, simulate={"fail_times": 2, "kind": "transient"})
        self.e.tick(); self.assertEqual(status(self.app, run["id"]), "RETRY_WAIT")
        self.e.tick(); self.assertEqual(status(self.app, run["id"]), "RETRY_WAIT")   # not yet visible
        self.clock.advance(2.1); self.e.tick(); self.assertEqual(status(self.app, run["id"]), "RETRY_WAIT")
        self.clock.advance(4.1); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 1)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM workflow_attempts")["c"], 3)

    def test_max_attempts_exhausted_goes_to_dlq(self):
        run = start(self.app, approval=False, simulate={"fail_times": 9, "kind": "transient"})
        for _ in range(6):
            self.e.tick(); self.clock.advance(10)
        self.assertEqual(status(self.app, run["id"]), "DEAD_LETTERED")
        d = self.s.q("SELECT * FROM dead_letters")[0]
        self.assertEqual((d["kind"], d["error_class"], d["status"]), ("workflow", "transient_exhausted", "OPEN"))
        self.assertTrue(d["payload_hash"]); self.assertEqual(len(json.loads(d["attempt_history_json"])), 3)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 0)

    def test_retry_window_limit(self):
        self.e.cfg.max_retry_window_s = 1
        run = start(self.app, approval=False, simulate={"fail_times": 9, "kind": "transient"})
        self.e.tick()   # first delay 2s > window 1s
        self.assertEqual(status(self.app, run["id"]), "DEAD_LETTERED")

    def test_permanent_failure_not_retried(self):
        run = start(self.app, approval=False, simulate={"fail_times": 1, "kind": "permanent"})
        self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "FAILED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM workflow_attempts")["c"], 1)
        with self.assertRaises(Refused): self.e.retry_run(run["id"], "t")   # not safely retryable

    def test_timeout_is_transient(self):
        self.e.cfg.step_timeout_s = 5
        run = start(self.app, approval=False, simulate={"slow_s": 60})
        self.e.tick()
        self.assertEqual(status(self.app, run["id"]), "RETRY_WAIT")
        a = self.s.one("SELECT * FROM workflow_attempts"); self.assertEqual(a["error_class"], "timeout")

    def test_backoff_deterministic_and_jitter_bounded(self):
        import random
        b = Backoff(jitter=0); self.assertEqual([b.delay(i) for i in (1, 2, 3)], [2, 4, 8])
        bj = Backoff(jitter=0.2, rng=random.Random(1))
        for i in range(1, 6): self.assertTrue(0.8 * min(300, 2 * 2 ** (i - 1)) <= bj.delay(i) <= 1.2 * min(300, 2 * 2 ** (i - 1)))


class LifecycleControls(Base):
    def test_cancel_closes_queue_and_blocks_execution(self):
        run = start(self.app, approval=False)
        self.e.cancel_run(run["id"], "tester"); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "CANCELLED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 0)

    def test_cancel_waiting_run(self):
        run = start(self.app); self.e.drain(); self.e.cancel_run(run["id"], "tester")
        self.assertEqual(self.s.one("SELECT status FROM approvals")["status"], "REVOKED")
        with self.assertRaises(Exception): grant(self.app, run["id"])

    def test_pause_and_resume(self):
        run = start(self.app, approval=False)
        self.e.pause_run(run["id"], "t"); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "PAUSED")
        self.e.resume_paused(run["id"], "t"); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")
        run2 = start(self.app); self.e.drain()
        with self.assertRaises(Refused): self.e.pause_run(run2["id"], "t")

    def test_crash_recovery_lease_expiry(self):
        run = start(self.app, approval=False)
        claimed = self.e._claim(1)            # worker "crashes" after claiming, before processing
        self.assertEqual(len(claimed), 1)
        self.assertEqual(self.e.tick()["processed"], 0)     # still leased
        self.clock.advance(61)
        self.e.drain(); self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 1)

    def test_recover_after_restart_mid_run(self):
        run = start(self.app, approval=False)
        self.e._claim(1)
        self.s.x("UPDATE workflow_runs SET status='RUNNING' WHERE id=?", (run["id"],))
        self.e.recover(); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")

    def test_graceful_stop(self):
        import threading
        t = threading.Thread(target=self.e.run_forever); self.e.cfg.worker_interval_s = 0.01
        t.start(); self.e.stop(); t.join(2); self.assertFalse(t.is_alive())


class IdempotencyTests(Base):
    def test_same_idempotency_key_returns_same_run(self):
        a, c1 = self.e.start_run({"workflow_type": "sample.governed_action", "payload": {}, "idempotency_key": "k1"})
        b, c2 = self.e.start_run({"workflow_type": "sample.governed_action", "payload": {}, "idempotency_key": "k1"})
        self.assertEqual((a["id"], c1, c2), (b["id"], True, False))
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM workflow_runs")["c"], 1)
        with self.assertRaises(Conflict):
            self.e.start_run({"workflow_type": "sample.governed_action", "payload": {"marker": "different"}, "idempotency_key": "k1"})

    def test_duplicate_queue_events_do_not_duplicate_side_effects(self):
        run = start(self.app, approval=False)
        _, created = self.e._enqueue(run["id"], "step", f"run:{run['id']}:start", run["correlation_id"])
        self.assertFalse(created)
        # a second, differently-keyed message for the same run (duplicate delivery) must not repeat effects
        self.e._enqueue(run["id"], "step", "dup-key-2", run["correlation_id"])
        self.e.drain()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM side_effects")["c"], 1)
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notifications")["c"], 1)

    def test_bounded_queue(self):
        from aegisnova_ops.engine import QueueFull
        self.e.cfg.queue_max_depth = 2
        start(self.app, approval=False); start(self.app, approval=False)
        with self.assertRaises(QueueFull): start(self.app, approval=False)

    def test_bounded_concurrency_per_tick(self):
        self.e.cfg.concurrency = 2
        for _ in range(5): start(self.app, approval=False)
        self.assertEqual(self.e.tick()["processed"], 2)


class OutboxTests(Base):
    def test_outbox_atomic_with_completion(self):
        run = start(self.app, approval=False)
        orig = self.e._transition
        def boom(*a, **k):
            if a[1] == "SUCCEEDED": raise RuntimeError("crash before commit")
            return orig(*a, **k)
        self.e._transition = boom
        self.e.tick()
        self.e._transition = orig
        # nothing half-written: no notification without completion
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notifications")["c"], 0)
        self.assertNotEqual(status(self.app, run["id"]), "SUCCEEDED")
        self.clock.advance(10); self.e.drain()
        self.assertEqual(status(self.app, run["id"]), "SUCCEEDED")
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notifications")["c"], 1)

    def test_stale_sending_reconciled_conservatively(self):
        start(self.app, approval=False); self.e.tick()   # processes run, notification CREATED
        n = self.s.one("SELECT * FROM notifications")
        before = self.s.one("SELECT COUNT(*) c FROM notification_attempts")["c"]
        self.s.x("UPDATE notifications SET status='SENDING', updated_at=? WHERE id=?", (self.clock.now_iso(), n["id"]))
        self.clock.advance(self.e.cfg.notif_stale_sending_s + 1)
        self.assertEqual(self.e.reconcile_stale_sending(), 1)
        self.assertEqual(self.s.one("SELECT status FROM notifications")["status"], "UNKNOWN")
        self.e.deliver_notifications()
        self.assertEqual(self.s.one("SELECT COUNT(*) c FROM notification_attempts")["c"], before)  # not resent
