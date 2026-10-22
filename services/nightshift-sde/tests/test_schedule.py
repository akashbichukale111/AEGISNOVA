"""Scheduler tests. All data is TEST DATA (synthetic fixtures, fake clock)."""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nightshift.errors import Conflict, ValidationError
from nightshift.schedule import local_to_utc, next_after, validate_recurrence
from nightshift.util import UTC, iso
from tests.helpers import Env


def body(env, **kw):
    b = {"name": "nightly", "repo_id": env.repo("legacy-batch")["id"], "kind": "recurring", "timezone": "UTC",
         "recurrence": {"type": "daily", "at": "06:00"}}
    b.update(kw)
    return b


class RecurrenceMathTests(unittest.TestCase):
    def test_validate_recurrence_rejects_bad_input(self):
        for bad in ({"type": "cron"}, {"type": "daily", "at": "6:00"}, {"type": "daily", "at": "25:00"}, {"type": "interval", "every_minutes": 0},
                    {"type": "interval", "every_minutes": True}, {"type": "weekly", "days": [], "at": "01:00"},
                    {"type": "weekly", "days": ["funday"], "at": "01:00"}, "daily", None):
            with self.assertRaises(ValidationError, msg=str(bad)):
                validate_recurrence(bad)

    def test_weekly_normalises_and_picks_correct_weekday(self):
        rec = validate_recurrence({"type": "weekly", "days": ["fri", "mon", "mon"], "at": "09:30"})
        self.assertEqual(rec["days"], ["mon", "fri"])
        tz = ZoneInfo("UTC")
        nxt = next_after(rec, tz, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 20, 5, 0, tzinfo=UTC))  # Tuesday
        self.assertEqual((nxt.weekday(), nxt.hour, nxt.minute), (4, 9, 30))

    def test_next_after_is_strictly_greater(self):
        rec = {"type": "daily", "at": "06:00"}
        at = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
        self.assertEqual(next_after(rec, ZoneInfo("UTC"), at, at), at + timedelta(days=1))

    def test_dst_gap_shifts_forward_and_runs_once_per_day(self):
        ny = ZoneInfo("America/New_York")
        # 2026-03-08 02:30 does not exist in New York (spring forward 02:00 -> 03:00)
        u = local_to_utc(datetime(2026, 3, 8).date(), datetime(2026, 3, 8, 2, 30).time(), ny)
        self.assertEqual(u.astimezone(ny).strftime("%H:%M"), "03:30")
        rec = {"type": "daily", "at": "02:30"}
        cur, seen = datetime(2026, 3, 6, 12, 0, tzinfo=UTC), []
        for _ in range(4):
            cur = next_after(rec, ny, datetime(2026, 3, 1, tzinfo=UTC), cur)
            seen.append(cur.astimezone(ny).date())
        self.assertEqual(len(set(seen)), 4)  # no day skipped or doubled

    def test_dst_overlap_picks_first_occurrence_once(self):
        ny = ZoneInfo("America/New_York")
        # 2026-11-01 01:30 happens twice; we choose the first (EDT, UTC-4) => 05:30Z
        u = local_to_utc(datetime(2026, 11, 1).date(), datetime(2026, 11, 1, 1, 30).time(), ny)
        self.assertEqual(u, datetime(2026, 11, 1, 5, 30, tzinfo=UTC))
        rec = {"type": "daily", "at": "01:30"}
        a = next_after(rec, ny, datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 11, 1, 0, 0, tzinfo=UTC))
        b = next_after(rec, ny, datetime(2026, 10, 1, tzinfo=UTC), a)
        self.assertEqual(a, u)
        self.assertEqual(b.astimezone(ny).date().isoformat(), "2026-11-02")

    def test_wall_clock_follows_local_time_across_dst(self):
        ny = ZoneInfo("America/New_York")
        rec = {"type": "daily", "at": "09:00"}
        anchor = datetime(2026, 3, 1, tzinfo=UTC)
        before = next_after(rec, ny, anchor, datetime(2026, 3, 6, 15, 0, tzinfo=UTC))   # EST (UTC-5) -> 14:00Z
        after = next_after(rec, ny, anchor, datetime(2026, 3, 9, 12, 0, tzinfo=UTC))
        self.assertEqual(before.astimezone(ny).hour, 9)
        self.assertEqual(after.astimezone(ny).hour, 9)
        self.assertNotEqual(before.hour, after.hour)  # UTC hour moved by DST


class ScheduleManagerTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.sm = self.env.app.schedules

    def tearDown(self):
        self.env.close()

    def test_create_computes_next_run_in_configured_timezone(self):
        s = self.sm.create(body(self.env, timezone="Asia/Kolkata", recurrence={"type": "daily", "at": "02:00"}), "alice")
        # clock = 2026-10-20 05:00Z = 10:30 IST -> next 02:00 IST is 2026-10-21 02:00 IST = 2026-10-20 20:30Z
        self.assertTrue(s["next_run_at"].startswith("2026-10-20T20:30:00"))
        self.assertEqual(s["status"], "active")
        self.assertIn("Asia/Kolkata", s["recurrence_text"])

    def test_validate_is_a_dry_run(self):
        out = self.sm.validate(body(self.env))
        self.assertTrue(out["valid"])
        self.assertEqual(len(out["next_runs"]), 5)
        self.assertEqual([s["name"] for s in self.sm.list() if s["name"] == "nightly"], [])

    def test_server_side_validation_errors(self):
        cases = [
            (dict(timezone="Mars/Olympus"), "INVALID_TIMEZONE"),
            (dict(recurrence={"type": "daily", "at": "99:99"}), "INVALID_RECURRENCE"),
            (dict(kind="weekly"), "INVALID_KIND"),
            (dict(name=""), "INVALID_NAME"),
            (dict(repo_id="rep_nope"), None),
            (dict(allow_repair=True), "REPAIR_NOT_PERMITTED_FOR_REPO"),  # legacy-batch is not repair-capable
            (dict(retry_policy={"max_attempts": 99}), "INVALID_RETRY_POLICY"),
            (dict(misfire_policy="burst"), None),
            (dict(bogus=1), "UNKNOWN_FIELD"),
            (dict(kind="one_time", run_at_local="2020-01-01T00:00"), "INVALID_RUN_AT"),
            (dict(kind="one_time", run_at_local="2030-01-01T00:00+05:30"), "INVALID_RUN_AT"),
        ]
        for kw, code in cases:
            with self.assertRaises((ValidationError, Exception), msg=str(kw)) as cm:
                self.sm.create(body(self.env, **kw), "alice")
            if code:
                self.assertEqual(getattr(cm.exception, "code", None), code, kw)

    def test_duplicate_name_per_repo_conflicts(self):
        self.sm.create(body(self.env), "alice")
        with self.assertRaises(Conflict):
            self.sm.create(body(self.env), "alice")

    def test_pause_resume_enable_disable_cycle_and_audit(self):
        s = self.sm.create(body(self.env), "alice")
        for action, status in (("pause", "paused"), ("resume", "active"), ("disable", "disabled"), ("enable", "active")):
            self.assertEqual(self.sm.set_status(s["id"], action, "alice")["status"], status)
        with self.assertRaises(ValidationError):
            self.sm.set_status(s["id"], "explode", "alice")
        types = [r["type"] for r in self.env.app._q("SELECT type FROM events WHERE schedule_id=? ORDER BY id", (s["id"],))]
        self.assertEqual(types[:5], ["schedule.created", "schedule.pause", "schedule.resume", "schedule.disable", "schedule.enable"])

    def test_paused_or_disabled_schedule_does_not_fire(self):
        s = self.sm.create(body(self.env), "alice")
        self.sm.set_status(s["id"], "pause", "alice")
        self.env.clock.advance(3 * 86400)
        self.assertEqual(self.env.app.scheduler.tick(), [])
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 0)

    def test_resume_after_pause_has_no_catch_up_burst(self):
        s = self.sm.create(body(self.env), "alice")
        self.sm.set_status(s["id"], "pause", "alice")
        self.env.clock.advance(5 * 86400)
        r = self.sm.set_status(s["id"], "resume", "alice")
        self.assertGreater(r["next_run_at"], iso(self.env.clock.now()))
        self.assertEqual(self.env.app.scheduler.tick(), [])

    def test_soft_delete_stops_runs_and_hides_schedule(self):
        s = self.sm.create(body(self.env), "alice")
        self.sm.delete(s["id"], "alice")
        self.env.clock.advance(2 * 86400)
        self.assertEqual(self.env.app.scheduler.tick(), [])
        self.assertEqual(self.sm.list(), [])

    def test_update_recomputes_next_run(self):
        s = self.sm.create(body(self.env), "alice")
        u = self.sm.update(s["id"], {"recurrence": {"type": "daily", "at": "23:00"}}, "alice")
        self.assertTrue(u["next_run_at"].startswith("2026-10-20T23:00"))


class SchedulerTickTests(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.sm = self.env.app.schedules
        self.sched = self.env.app.scheduler

    def tearDown(self):
        self.env.close()

    def _make(self, **kw):
        return self.sm.create(body(self.env, **kw), "alice")

    def test_fires_once_when_due_and_creates_scheduled_investigation_job(self):
        s = self._make()
        self.assertEqual(self.sched.tick(), [])  # not due yet
        self.env.clock.advance(3601)  # 06:00:01 (clock starts 05:00)
        fired = self.sched.tick()
        self.assertEqual([f["status"] for f in fired], ["fired"])
        job = self.env.job(fired[0]["job_id"])
        self.assertEqual((job["trigger_type"], bool(job["allow_repair"]), job["schedule_id"]), ("schedule", False, s["id"]))
        self.assertEqual(self.sched.tick(), [])  # a second tick at the same instant fires nothing
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 1)

    def test_overlapping_ticks_from_threads_do_not_double_fire(self):
        import threading
        self._make()
        self.env.clock.advance(3601)
        results = []

        def go():
            results.append(self.sched.tick())
        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sum(len(r) for r in results), 1)
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs WHERE trigger_type='schedule'")["n"], 1)
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM schedule_runs")["n"], 1)

    def test_unique_constraint_backstop_suppresses_duplicate_slot(self):
        s = self._make()
        self.env.clock.advance(3601)
        first = self.sched.tick()
        # simulate a lost "next_run_at" update (e.g. a restored backup): the same slot becomes due again
        self._reset(s["id"], first[0]["scheduled_for"])
        second = self.sched.tick()
        self.assertEqual(second[0]["status"], "duplicate_suppressed")
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 1)
        self.assertEqual(self.env.store.counter("duplicate_trigger_suppressed"), 1)

    def _reset(self, sid, when):
        with self.env.app.db.tx() as c:
            c.execute("UPDATE schedules SET next_run_at=? WHERE id=?", (when, sid))

    def test_missed_run_after_downtime_skip_policy(self):
        s = self._make(misfire_policy="skip", misfire_grace_seconds=300)
        self.env.clock.advance(3 * 86400 + 7200)  # "process was down" for 3 days
        fired = self.sched.tick()
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["status"], "missed_skipped")
        self.assertIsNone(fired[0]["job_id"])
        self.assertGreaterEqual(fired[0]["missed_older_slots"], 2)
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 0)
        nxt = self.sm.get(s["id"])["next_run_at"]
        self.assertGreater(nxt, iso(self.env.clock.now()))  # re-armed in the future: no storm

    def test_missed_run_after_downtime_run_once_policy_collapses_backlog(self):
        self._make(misfire_policy="run_once", misfire_grace_seconds=300)
        self.env.clock.advance(3 * 86400 + 7200)
        fired = self.sched.tick()
        self.assertEqual([f["status"] for f in fired], ["catchup_fired"])
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 1)  # one job, not one per missed day
        self.assertGreaterEqual(self.env.store.counter("schedule_runs_missed"), 2)

    def test_within_grace_is_a_normal_fire(self):
        self._make(misfire_grace_seconds=600)
        self.env.clock.advance(3600 + 100)
        self.assertEqual(self.sched.tick()[0]["status"], "fired")

    def test_forbid_concurrency_skips_while_previous_job_open(self):
        self._make(recurrence={"type": "interval", "every_minutes": 10}, concurrency_policy="forbid")
        self.env.clock.advance(601)
        self.assertEqual(self.sched.tick()[0]["status"], "fired")  # job stays QUEUED (no worker runs)
        self.env.clock.advance(600)
        self.assertEqual(self.sched.tick()[0]["status"], "skipped_concurrency")
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 1)

    def test_allow_concurrency_fires_again(self):
        self._make(recurrence={"type": "interval", "every_minutes": 10}, concurrency_policy="allow")
        self.env.clock.advance(601)
        self.sched.tick()
        self.env.clock.advance(600)
        self.assertEqual(self.sched.tick()[0]["status"], "fired")
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 2)

    def test_one_time_schedule_fires_once_then_completes(self):
        s = self._make(kind="one_time", recurrence=None, run_at_local="2026-10-20T06:00", timezone="UTC", name="once")
        self.env.clock.advance(3700)
        self.assertEqual(self.sched.tick()[0]["status"], "fired")
        done = self.sm.get(s["id"])
        self.assertEqual((done["status"], done["next_run_at"]), ("completed", None))
        self.env.clock.advance(86400)
        self.assertEqual(self.sched.tick(), [])
        with self.assertRaises(Conflict):
            self.sm.set_status(s["id"], "enable", "alice")

    def test_scheduled_job_is_never_repair_capable_unless_explicit_and_repo_allows(self):
        pay = self.env.repo("payments-service")
        a = self.sm.create(body(self.env, repo_id=pay["id"], name="ro"), "alice")
        b = self.sm.create(body(self.env, repo_id=pay["id"], name="rw", allow_repair=True), "alice")
        self.env.clock.advance(3700)
        fired = {f["schedule_id"]: self.env.job(f["job_id"]) for f in self.sched.tick() if f["job_id"]}
        self.assertFalse(fired[a["id"]]["allow_repair"])
        self.assertTrue(fired[b["id"]]["allow_repair"])

    def test_repair_flag_is_downgraded_if_repo_lost_repair_capability_at_fire_time(self):
        pay = self.env.repo("payments-service")
        s = self.sm.create(body(self.env, repo_id=pay["id"], name="rw", allow_repair=True), "alice")
        with self.env.app.db.tx() as c:
            c.execute("UPDATE repositories SET allow_repair=0 WHERE id=?", (pay["id"],))
        self.env.clock.advance(3700)
        f = self.sched.tick()[0]
        self.assertFalse(self.env.job(f["job_id"])["allow_repair"])
        self.assertEqual(s["id"], f["schedule_id"])

    def test_restart_behaviour_state_lives_in_db_not_memory(self):
        """A brand-new App over the same database (process restart) must not re-fire an already fired slot."""
        import random
        from nightshift.service import App
        self._make()
        self.env.clock.advance(3601)
        self.assertEqual(len(self.sched.tick()), 1)
        app2 = App(self.env.settings, clock=self.env.clock, rng=random.Random(1))
        self.assertEqual(app2.scheduler.tick(), [])
        self.assertEqual(self.env.app._q1("SELECT COUNT(*) AS n FROM jobs")["n"], 1)
        app2.db.close()


if __name__ == "__main__":
    unittest.main()
