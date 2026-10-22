"""Watchdog tests. All data is TEST DATA (synthetic fixtures, fake clock)."""
import unittest

from nightshift import statemachine as sm
from tests.helpers import Env


def alerts(env, kind=None, status="open"):
    rows = env.app._q("SELECT * FROM alerts WHERE status=?", (status,))
    return [r for r in rows if kind is None or r["kind"] == kind]


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.store = self.env.store
        self.wd = self.env.app.watchdog

    def tearDown(self):
        self.env.close()

    def _job(self, slug="legacy-batch", **kw):
        return self.env.trigger(slug, **kw)

    def test_expired_lease_is_reclaimed_fenced_and_alerted_with_recommendation(self):
        job = self._job()
        j = self.store.claim_next("w1", 60)
        self.env.clock.advance(61)
        out = self.wd.tick()
        self.assertEqual(out["leases_reclaimed"], 1)
        a = alerts(self.env, "lease_expired")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["subject_id"], job["id"])
        self.assertTrue(a[0]["recommended_action"])
        self.assertEqual(a[0]["auto_recovery_attempted"], 1)
        self.assertTrue(a[0]["correlation_id"])
        self.assertIsNone(self.env.job(job["id"])["lease_owner"])
        from nightshift.errors import LeaseLost
        with self.assertRaises(LeaseLost):
            self.store.heartbeat(job["id"], "w1", j["fence"], 60)

    def test_alerts_are_deduplicated_and_resolve_when_condition_clears(self):
        self._job()
        self.store.claim_next("w1", 60)
        self.env.clock.advance(61)
        self.wd.tick()
        self.wd.tick()
        self.assertEqual(len(alerts(self.env, "lease_expired")), 1)
        # the lease_expired alert is keyed by fence; it resolves once no longer firing
        self.env.clock.advance(1000)
        self.wd.tick()
        self.assertEqual(len(alerts(self.env, "lease_expired")), 0)
        self.assertEqual(len(alerts(self.env, "lease_expired", "resolved")), 1)

    def test_progress_stall_with_live_lease(self):
        job = self._job()
        j = self.store.claim_next("w1", 60)
        self.env.settings.progress_stall_seconds = 120
        for _ in range(3):  # keep the lease alive but make no progress
            self.env.clock.advance(50)
            self.store.heartbeat(job["id"], "w1", j["fence"], 60)
        self.wd.tick()
        a = alerts(self.env, "progress_stalled")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["reason_code"], "NO_PROGRESS")

    def test_waiting_for_approval_is_not_reported_as_stalled(self):
        job = self.env.to_waiting()
        self.env.clock.advance(3600)
        self.wd.tick()
        self.assertEqual(alerts(self.env, "progress_stalled"), [])
        self.assertEqual(self.env.job(job["id"])["state"], "WAITING_FOR_APPROVAL")

    def test_stuck_waiting_for_approval_beyond_expiry_expires_job_and_never_approves(self):
        job = self.env.to_waiting()
        self.env.clock.advance(self.env.settings.approval_ttl_seconds + 5)
        out = self.wd.tick()
        self.assertGreaterEqual(out["approvals_expired"], 1)
        j = self.env.job(job["id"])
        self.assertEqual((j["state"], j["outcome"]), (sm.EXPIRED, "approval_expired"))
        statuses = [r["status"] for r in self.env.app._q("SELECT status FROM approvals WHERE job_id=?", (job["id"],))]
        self.assertEqual(statuses, ["expired"])
        self.assertNotIn("approved", statuses)
        # expired job can never be executed by a worker
        self.assertIsNone(self.store.claim_next("w9", 60))
        self.assertIn("APPROVAL_EXPIRED", self.env.reasons(job["id"]))

    def test_missed_schedule_alert_when_scheduler_is_not_running(self):
        self.env.app.schedules.create({"name": "n", "repo_id": self.env.repo("legacy-batch")["id"], "kind": "recurring",
                                       "timezone": "UTC", "recurrence": {"type": "daily", "at": "06:00"}}, "alice")
        self.env.clock.advance(3600 + 600)  # 10 minutes past due, scheduler never ticked
        self.wd.tick()
        a = alerts(self.env, "schedule_missed")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["severity"], "high")
        self.assertTrue(a[0]["recommended_action"])
        # once the scheduler fires, the alert auto-resolves
        self.env.app.scheduler.tick()
        self.wd.tick()
        self.assertEqual(alerts(self.env, "schedule_missed"), [])

    def test_dead_letter_growth_alert(self):
        self.env.settings.dlq_alert_count = 2
        for slug in ("legacy-batch", "payments-service"):
            job = self._job(slug)
            for _ in range(4):
                self.env.clock.advance(301)
                j = self.store.claim_next("w1", 60)
                self.store.fail_transient(job["id"], fence=j["fence"], worker_id="w1", code="PROVIDER_UNAVAILABLE", message="down")
            self.assertEqual(self.env.job(job["id"])["state"], sm.DEAD_LETTER)
        self.wd.tick()
        a = alerts(self.env, "dlq_growth")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["severity"], "high")

    def test_queue_age_alert_and_no_alert_for_fresh_queue(self):
        self._job()
        self.wd.tick()
        self.assertEqual(alerts(self.env, "queue_age"), [])
        self.env.clock.advance(self.env.settings.queue_age_alert_seconds + 5)
        self.wd.tick()
        a = alerts(self.env, "queue_age")
        self.assertEqual(len(a), 1)
        self.assertIn("worker", a[0]["recommended_action"].lower())

    def test_queue_depth_alert(self):
        self.env.settings.queue_depth_alert = 3
        for _ in range(3):
            self._job()
        self.wd.tick()
        self.assertEqual(len(alerts(self.env, "queue_depth")), 1)

    def test_crash_loop_alert_after_repeated_lease_losses(self):
        job = self._job()
        for _ in range(3):
            self.env.clock.advance(301)
            self.store.claim_next("w1", 60)
            self.env.clock.advance(61)
            self.wd.tick()
        a = alerts(self.env, "crash_loop")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["subject_id"], job["id"])

    def test_watchdog_recovery_cannot_bypass_approval_gate(self):
        """A lease lost during a gated job must never turn into an approved/applied repair."""
        job = self.env.to_waiting()
        before = self.env.tree_snapshot("payments-service")
        self.env.clock.advance(120)
        self.wd.tick()
        self.assertEqual(self.env.job(job["id"])["state"], "WAITING_FOR_APPROVAL")
        self.assertIsNone(self.store.claim_next("w2", 60))  # nobody can run it without a human decision
        self.assertEqual(self.env.tree_snapshot("payments-service"), before)
        self.assertEqual([r["status"] for r in self.env.app._q("SELECT status FROM approvals WHERE job_id=?", (job["id"],))], ["pending"])

    def test_orphaned_workspace_is_removed_and_reported_as_auto_recovery(self):
        import os
        import time
        d = self.env.settings.workspaces_dir / "job_unknown_orphan"
        d.mkdir(parents=True)
        (d / "f.txt").write_text("x")
        old = time.time() - 600
        os.utime(d, (old, old))
        out = self.wd.tick()
        self.assertEqual(out["workspaces_removed"], 1)
        self.assertFalse(d.exists())
        a = alerts(self.env, "orphaned_workspace")
        self.assertEqual(a[0]["auto_recovery_attempted"], 1)

    def test_provider_failure_alert(self):
        with self.env.app.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO provider_health(provider, mode, status, consecutive_failures, last_error_code) VALUES ('osv', 'live', 'down', 5, 'PROVIDER_UNAVAILABLE')")
        self.wd.tick()
        a = alerts(self.env, "provider_failures")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["subject_id"], "osv")


if __name__ == "__main__":
    unittest.main()
