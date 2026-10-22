import threading
import unittest
from datetime import timedelta

from nightshift import statemachine as sm
from nightshift.errors import Conflict, InvalidTransition, LeaseLost, RateLimited
from nightshift.retry import normalize_policy
from nightshift.util import iso
from tests.helpers import ADMIN, Env, PASSING_TESTS


def mk_job(env, slug="legacy-batch", **kw):
    return env.trigger(slug, **kw)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.store = self.env.store

    def tearDown(self):
        self.env.close()

    # ---- idempotency
    def test_trigger_idempotency_key_returns_same_job_and_counts_duplicate(self):
        a = self.env.trigger("legacy-batch", key="idem-key-0001")
        b = self.env.trigger("legacy-batch", key="idem-key-0001")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(self.store.counter("duplicate_trigger_suppressed"), 1)
        n = self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"]
        self.assertEqual(n, 1)

    def test_queue_cap_rate_limits_per_repository(self):
        self.env.settings.queue_cap_per_repo = 2
        self.env.trigger("legacy-batch")
        self.env.trigger("legacy-batch")
        with self.assertRaises(RateLimited):
            self.env.trigger("legacy-batch")

    # ---- transitions
    def test_transition_is_validated_persisted_and_audited(self):
        job = mk_job(self.env)
        with self.assertRaises(InvalidTransition):
            self.store.transition(job["id"], sm.EXECUTING, actor="t", source="test", reason_code="X")
        self.assertEqual(self.env.job(job["id"])["state"], sm.QUEUED)
        rows = self.store.list_transitions(job["id"])
        self.assertEqual([r["to_state"] for r in rows], ["CREATED", "QUEUED"])
        for r in rows:
            self.assertTrue(r["actor"] and r["source"] and r["reason_code"] and r["correlation_id"] and r["at"])
        self.assertTrue(self.store.verify_chain()["ok"])

    def test_transition_is_atomic_if_audit_write_fails(self):
        job = mk_job(self.env)
        original = self.store.emit
        self.store.emit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            with self.assertRaises(RuntimeError):
                self.store.transition(job["id"], sm.PAUSED, actor="t", source="test", reason_code="X")
        finally:
            self.store.emit = original
        self.assertEqual(self.env.job(job["id"])["state"], sm.QUEUED)  # rolled back
        self.assertEqual(len(self.store.list_transitions(job["id"])), 2)

    def test_terminal_invariants(self):
        job = mk_job(self.env)
        self.env.drain()
        j = self.env.job(job["id"])
        self.assertIn(j["state"], sm.TERMINAL)
        self.assertIsNone(j["lease_owner"])
        self.assertIsNone(j["lease_expires_at"])
        self.assertTrue(j["finished_at"])
        self.assertTrue(j["outcome"])
        for to in sm.ALL_STATES:
            with self.assertRaises(InvalidTransition):
                self.store.transition(job["id"], to, actor="t", source="test", reason_code="X")

    def test_audit_log_is_append_only_and_chain_detects_tampering(self):
        mk_job(self.env)
        c = self.env.app.db.conn()
        with self.assertRaises(Exception):
            c.execute("UPDATE events SET actor='evil' WHERE id=1")
        with self.assertRaises(Exception):
            c.execute("DELETE FROM events")
        with self.assertRaises(Exception):
            c.execute("UPDATE job_transitions SET reason_code='x'")
        self.assertTrue(self.store.verify_chain()["ok"])
        # simulate an attacker with raw DB access who drops the trigger and edits a row
        c.execute("DROP TRIGGER events_no_update")
        c.execute("UPDATE events SET actor='evil' WHERE id=2")
        r = self.store.verify_chain()
        self.assertFalse(r["ok"])
        self.assertEqual(r["broken_at_event"], 2)

    # ---- leases, claims, fencing
    def test_claim_sets_lease_fence_attempt(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        self.assertEqual((j["id"], j["state"], j["attempt"], j["fence"], j["lease_owner"]), (job["id"], "VALIDATING", 1, 1, "w1"))
        self.assertEqual(j["lease_expires_at"], iso(self.env.clock.now() + timedelta(seconds=60)))
        self.assertIsNone(self.store.claim_next("w2", 60))  # nothing else runnable

    def test_two_workers_cannot_claim_the_same_job_concurrently(self):
        mk_job(self.env)
        results, barrier = [], threading.Barrier(6)

        def go(i):
            barrier.wait()
            results.append(self.store.claim_next(f"w{i}", 60))
            self.env.app.db.close()
        ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len([r for r in results if r]), 1)

    def test_per_repo_concurrency_limit(self):
        a, b = mk_job(self.env), mk_job(self.env)
        self.assertIsNotNone(self.store.claim_next("w1", 60))
        self.assertIsNone(self.store.claim_next("w2", 60))  # repo limit is 1
        self.assertEqual(self.env.job(b["id"])["state"], "QUEUED")

    def test_expired_lease_fences_out_stale_worker(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        fence1 = j["fence"]
        self.env.clock.advance(61)
        reclaimed = self.store.reclaim_expired_leases()
        self.assertEqual(len(reclaimed), 1)
        r = self.env.job(job["id"])
        self.assertEqual(r["state"], sm.RETRY_WAIT)
        self.assertIsNone(r["lease_owner"])
        self.assertGreater(r["fence"], fence1)
        # the old worker wakes up and tries to write: every fenced write is refused
        with self.assertRaises(LeaseLost):
            self.store.transition(job["id"], sm.SNAPSHOTTING, actor="w1", source="worker", reason_code="X", fence=fence1, worker_id="w1")
        with self.assertRaises(LeaseLost):
            self.store.save_checkpoint(job["id"], fence=fence1, worker_id="w1", stage="snapshot", data={}, base_tree="t", base_commit=None,
                                       policy_name=None, policy_version=None)
        with self.assertRaises(LeaseLost):
            self.store.heartbeat(job["id"], "w1", fence1, 60)
        self.assertEqual(self.store.counter("lease_expiries"), 1)

    def test_new_worker_takes_over_after_expiry_and_old_one_stays_fenced(self):
        job = mk_job(self.env)
        j1 = self.store.claim_next("w1", 60)
        self.env.clock.advance(61)
        self.store.reclaim_expired_leases()
        self.env.clock.advance(400)  # past any backoff
        j2 = self.store.claim_next("w2", 60)
        self.assertEqual((j2["lease_owner"], j2["attempt"]), ("w2", 2))
        self.assertGreater(j2["fence"], j1["fence"])
        with self.assertRaises(LeaseLost):
            self.store.heartbeat(job["id"], "w1", j1["fence"], 60)
        self.store.heartbeat(job["id"], "w2", j2["fence"], 60)  # legitimate owner still fine

    # ---- retry / dead letter
    def test_transient_failures_back_off_then_dead_letter_with_bounded_budget(self):
        job = mk_job(self.env)
        delays = []
        for i in range(4):
            self.env.clock.advance(301)  # past the max backoff (300s) but inside the 3600s retry window
            j = self.store.claim_next("w1", 60)
            self.assertIsNotNone(j, f"attempt {i}")
            out = self.store.fail_transient(job["id"], fence=j["fence"], worker_id="w1", code="PROVIDER_UNAVAILABLE", message="down")
            if out["state"] == sm.RETRY_WAIT:
                delays.append((__import__("nightshift.util", fromlist=["parse_iso"]).parse_iso(out["retry_at"]) - self.env.clock.now()).total_seconds())
        final = self.env.job(job["id"])
        self.assertEqual(final["state"], sm.DEAD_LETTER)
        self.assertEqual(final["outcome"], "dead_lettered")
        self.assertEqual(final["failed_attempts"], 4)
        self.assertEqual(len(delays), 3)
        for n, d in enumerate(delays, 1):
            ceiling = min(300.0, 5.0 * 2 ** (n - 1))
            self.assertTrue(ceiling / 2 - 0.01 <= d <= ceiling + 0.01, (n, d))
        self.assertEqual(final["error"]["code_final"], "RETRIES_EXHAUSTED")
        self.assertTrue(final["error"]["recovery"])
        self.assertEqual(self.store.counter("dead_lettered"), 1)

    def test_attempt_history_is_preserved_across_retries(self):
        job = mk_job(self.env)
        for _ in range(2):
            self.env.clock.advance(1000)
            j = self.store.claim_next("w1", 60)
            self.store.fail_transient(job["id"], fence=j["fence"], worker_id="w1", code="PROVIDER_UNAVAILABLE", message="down")
        attempts = self.env.app._q("SELECT attempt_no, end_state FROM job_attempts WHERE job_id=? ORDER BY attempt_no", (job["id"],))
        self.assertEqual([a["attempt_no"] for a in attempts], [1, 2])
        self.assertEqual([a["end_state"] for a in attempts], ["RETRY_WAIT", "RETRY_WAIT"])

    def test_permanent_failure_is_not_retried(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        out = self.store.fail_permanent(job["id"], fence=j["fence"], worker_id="w1", code="PROVIDER_AUTH_FAILED", message="401")
        self.assertEqual((out["state"], out["outcome"]), (sm.FAILED, "failed"))
        self.assertEqual(out["error"]["kind"], "permanent")
        self.assertIsNone(self.store.claim_next("w2", 60))

    def test_retry_window_exceeded_goes_to_dead_letter(self):
        job = self.env.app.store.create_job(repo_id=self.env.repo("legacy-batch")["id"], trigger_type="manual", idempotency_key="k-window-0001",
                                            requested_by="t", retry_policy={"max_attempts": 9, "max_elapsed_seconds": 100})[0]
        j = self.store.claim_next("w1", 60)
        self.env.clock.advance(500)
        out = self.store.fail_transient(job["id"], fence=j["fence"], worker_id="w1", code="PROVIDER_UNAVAILABLE", message="down")
        self.assertEqual(out["state"], sm.DEAD_LETTER)
        self.assertEqual(out["error"]["code_final"], "RETRY_WINDOW_EXCEEDED")

    def test_deadline_exceeded_expires_job(self):
        job = self.env.app.store.create_job(repo_id=self.env.repo("legacy-batch")["id"], trigger_type="manual", idempotency_key="k-deadline-01",
                                            requested_by="t", deadline_seconds=100)[0]
        j = self.store.claim_next("w1", 60)
        self.env.clock.advance(200)
        out = self.store.fail_transient(job["id"], fence=j["fence"], worker_id="w1", code="PROVIDER_UNAVAILABLE", message="down")
        self.assertEqual((out["state"], out["outcome"]), (sm.EXPIRED, "expired"))

    def test_job_expires_in_queue_when_deadline_passes(self):
        job = self.env.app.store.create_job(repo_id=self.env.repo("legacy-batch")["id"], trigger_type="manual", idempotency_key="k-deadline-02",
                                            requested_by="t", deadline_seconds=100)[0]
        self.env.clock.advance(101)
        self.assertIsNone(self.store.claim_next("w1", 60))
        self.assertEqual(self.env.job(job["id"])["state"], sm.EXPIRED)

    # ---- replay / cancel / pause
    def test_replay_creates_linked_job_and_preserves_original(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        self.store.fail_permanent(job["id"], fence=j["fence"], worker_id="w1", code="INVALID_DATA", message="bad")
        before = self.store.list_transitions(job["id"])
        new, created = self.store.replay_job(job["id"], "oscar", allow_repair=False)
        self.assertTrue(created)
        self.assertEqual((new["replay_of"], new["trigger_type"]), (job["id"], "replay"))
        self.assertEqual(self.store.list_transitions(job["id"]), before)  # original untouched
        again, created2 = self.store.replay_job(job["id"], "oscar", allow_repair=False)
        self.assertFalse(created2)
        self.assertEqual(again["id"], new["id"])  # no replay storms
        self.assertTrue(self.env.app._q("SELECT * FROM recovery_actions WHERE kind='replay'"))

    def test_only_terminal_jobs_can_be_replayed(self):
        job = mk_job(self.env)
        with self.assertRaises(Conflict):
            self.store.replay_job(job["id"], "oscar", allow_repair=False)

    def test_replay_cannot_escalate_to_repair(self):
        job = mk_job(self.env, "payments-service")
        j = self.store.claim_next("w1", 60)
        self.store.fail_permanent(job["id"], fence=j["fence"], worker_id="w1", code="INVALID_DATA", message="bad")
        new, _ = self.store.replay_job(job["id"], "oscar", allow_repair=False)
        self.assertFalse(new["allow_repair"])

    def test_cancel_queued_job_is_immediate(self):
        job = mk_job(self.env)
        out = self.store.request_cancel(job["id"], "oscar")
        self.assertEqual((out["state"], out["outcome"]), (sm.CANCELLED, "cancelled"))

    def test_cancel_running_job_goes_through_cancel_requested(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        out = self.store.request_cancel(job["id"], "oscar")
        self.assertEqual(out["state"], sm.CANCEL_REQUESTED)
        self.assertTrue(out["cancel_requested"])
        with self.assertRaises(Conflict):  # worker cannot continue the pipeline once cancel is requested
            self.store.transition(job["id"], sm.SNAPSHOTTING, actor="w1", source="worker", reason_code="X", fence=j["fence"], worker_id="w1",
                                  expect_from=sm.ACTIVE)

    def test_cancel_requested_with_dead_worker_is_cancelled_by_watchdog(self):
        job = mk_job(self.env)
        self.store.claim_next("w1", 60)
        self.store.request_cancel(job["id"], "oscar")
        self.env.clock.advance(61)
        self.store.reclaim_expired_leases()
        self.assertEqual(self.env.job(job["id"])["state"], sm.CANCELLED)

    def test_pause_and_resume_queued_job(self):
        job = mk_job(self.env)
        self.assertEqual(self.store.request_pause(job["id"], "oscar")["state"], sm.PAUSED)
        self.assertIsNone(self.store.claim_next("w1", 60))
        self.assertEqual(self.store.resume_job(job["id"], "oscar")["state"], sm.QUEUED)
        self.assertIsNotNone(self.store.claim_next("w1", 60))

    # ---- checkpoints
    def test_checkpoint_checksum_corruption_invalidates_it_and_successors(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        for stage in ("snapshot", "inspect", "research"):
            self.store.save_checkpoint(job["id"], fence=j["fence"], worker_id="w1", stage=stage, data={"s": stage}, base_tree="t", base_commit=None,
                                       policy_name=None, policy_version=None)
        self.assertEqual(list(self.store.valid_checkpoints(job["id"])), ["snapshot", "inspect", "research"])
        self.env.app.db.conn().execute("UPDATE checkpoints SET data='{\"s\":\"tampered\"}' WHERE stage='inspect'")
        self.assertEqual(list(self.store.valid_checkpoints(job["id"])), ["snapshot"])
        rows = self.env.app._q("SELECT stage, valid, invalidated_reason FROM checkpoints WHERE job_id=? ORDER BY seq", (job["id"],))
        self.assertEqual([(r["stage"], r["valid"]) for r in rows], [("snapshot", 1), ("inspect", 0), ("research", 0)])

    def test_invalidate_after_stage_keeps_history(self):
        job = mk_job(self.env)
        j = self.store.claim_next("w1", 60)
        for stage in ("snapshot", "inspect", "research"):
            self.store.save_checkpoint(job["id"], fence=j["fence"], worker_id="w1", stage=stage, data={}, base_tree="t", base_commit=None,
                                       policy_name=None, policy_version=None)
        self.assertEqual(self.store.invalidate_checkpoints(job["id"], after_stage="snapshot", reason="TEST"), 2)
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM checkpoints WHERE job_id=?", (job["id"],))["n"], 3)
        self.assertEqual(list(self.store.valid_checkpoints(job["id"])), ["snapshot"])


if __name__ == "__main__":
    unittest.main()
