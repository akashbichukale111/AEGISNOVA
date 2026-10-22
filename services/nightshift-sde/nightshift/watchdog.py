"""Watchdog: detects stuck/failed/late work, performs only SAFE automatic recovery, and records everything.

Safe automatic recovery is limited to: reclaiming expired leases (fencing the old worker out and routing through the bounded
retry logic), promoting due retries, expiring stale approvals, and deleting orphaned workspace directories.
It never approves anything, never bypasses a gate and never marks a job green.
Alerts are de-duplicated by ``dedupe_key`` while open and auto-resolve when the condition clears.
"""
from __future__ import annotations

import shutil
import time
from datetime import timedelta
from pathlib import Path

from . import statemachine as sm
from .store import Store
from .util import iso, jdumps, new_correlation_id, new_id, parse_iso

SEV_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class Watchdog:
    def __init__(self, store: Store, settings, governance, notifier=None):
        self.store, self.settings, self.gov, self.notifier = store, settings, governance, notifier

    # ------------------------------------------------------------------------------------ alert plumbing
    def _raise(self, firing: dict, *, kind, severity, subject_type, subject_id, repo_id, condition, reason_code, last_progress,
               recommended, key_suffix="", auto=False, result=None, corr=None) -> None:
        dedupe = f"{kind}:{subject_type}:{subject_id}{key_suffix}"
        firing[dedupe] = kind
        now = iso(self.store.clock.now())
        with self.store.db.tx() as c:
            if c.execute("SELECT 1 FROM alerts WHERE dedupe_key=? AND status='open'", (dedupe,)).fetchone():
                if result is not None:
                    c.execute("UPDATE alerts SET auto_recovery_attempted=?, recovery_result=? WHERE dedupe_key=? AND status='open'",
                              (1 if auto else 0, result, dedupe))
                return
            aid = new_id("alt")
            c.execute(
                "INSERT INTO alerts(id, kind, severity, subject_type, subject_id, repo_id, condition, reason_code, detected_at, last_progress,"
                " recommended_action, auto_recovery_attempted, recovery_result, correlation_id, status, dedupe_key)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, kind, severity, subject_type, subject_id, repo_id, condition, reason_code, now, last_progress, recommended,
                 1 if auto else 0, result, corr or new_correlation_id(), "open", dedupe))
            self.store.emit("watchdog.alert", actor="system:watchdog", correlation_id=corr, repo_id=repo_id,
                            job_id=subject_id if subject_type == "job" else None,
                            data={"alert_id": aid, "kind": kind, "severity": severity, "reason_code": reason_code, "condition": condition})
            self.store.incr("alerts_raised")
        if self.notifier and SEV_ORDER.get(severity, 0) >= SEV_ORDER["high"]:
            self.notifier.enqueue(None, f"alert:{dedupe}", {"kind": kind, "severity": severity, "condition": condition,
                                                             "recommended_action": recommended})

    # Alerts about a one-off EVENT (a lease expiry, a cleaned workspace) stay visible for a while instead of
    # resolving on the very next tick, otherwise an operator could never see them.
    EVENT_ALERT_KINDS = {"lease_expired", "orphaned_workspace"}
    EVENT_ALERT_TTL_SECONDS = 600

    def _resolve_cleared(self, firing: dict, kinds: set[str]) -> None:
        now_dt = self.store.clock.now()
        now = iso(now_dt)
        with self.store.db.tx() as c:
            for r in c.execute("SELECT id, dedupe_key, kind, detected_at FROM alerts WHERE status='open'").fetchall():
                if r["kind"] in self.EVENT_ALERT_KINDS and (now_dt - parse_iso(r["detected_at"])).total_seconds() < self.EVENT_ALERT_TTL_SECONDS:
                    continue
                if r["kind"] in kinds and r["dedupe_key"] not in firing:
                    c.execute("UPDATE alerts SET status='resolved', resolved_at=? WHERE id=?", (now, r["id"]))
                    self.store.emit("watchdog.alert_resolved", actor="system:watchdog", data={"alert_id": r["id"], "kind": r["kind"]})

    # ------------------------------------------------------------------------------------ main tick
    def tick(self) -> dict:
        s, st = self.settings, self.store
        now_dt = st.clock.now()
        now = iso(now_dt)
        firing: dict = {}
        summary = {"leases_reclaimed": 0, "retries_promoted": 0, "approvals_expired": 0, "workspaces_removed": 0, "alerts_open": 0}
        c = st.db.read()

        # ---- safe automatic recovery
        summary["retries_promoted"] = st.promote_due_retries()
        for job in st.reclaim_expired_leases():
            summary["leases_reclaimed"] += 1
            self._raise(firing, kind="lease_expired", severity="medium", subject_type="job", subject_id=job["id"], repo_id=job["repo_id"],
                        condition="worker lease expired; job was fenced and routed through bounded retry",
                        reason_code="LEASE_EXPIRED", last_progress=job.get("last_progress_note"),
                        recommended="No action needed unless it repeats: the job resumes from its last valid checkpoint.",
                        key_suffix=f":{job['fence']}", auto=True, result=f"job is now {job['state']}", corr=job["correlation_id"])
        expired = self.gov.expire_due()
        summary["approvals_expired"] = expired
        for j in c.execute("SELECT j.* FROM jobs j WHERE j.state=? AND NOT EXISTS (SELECT 1 FROM approvals a WHERE a.job_id=j.id AND a.status IN ('pending','approved'))",
                           (sm.WAITING_FOR_APPROVAL,)).fetchall():
            ex = c.execute("SELECT id FROM approvals WHERE job_id=? AND status='expired' ORDER BY requested_at DESC LIMIT 1", (j["id"],)).fetchone()
            if ex:
                try:
                    st.transition(j["id"], sm.EXPIRED, actor="system:watchdog", source="watchdog", reason_code="APPROVAL_EXPIRED",
                                  expect_from={sm.WAITING_FOR_APPROVAL},
                                  updates={"outcome": "approval_expired", "error": st._err("APPROVAL_EXPIRED", "approval expired before a decision", "permanent", "gate_blocked")})
                    st.record_recovery(job_id=j["id"], kind="approval_expired", actor="system:watchdog", source="watchdog", result="job expired",
                                       detail={"approval_id": ex["id"]}, correlation_id=j["correlation_id"])
                    summary["approvals_expired"] += 1
                except Exception:  # noqa: BLE001 — raced with a human decision; fine
                    pass

        # ---- job-level detectors
        for j in c.execute("SELECT * FROM jobs WHERE state NOT IN (%s)" % ",".join("?" * len(sm.TERMINAL)), tuple(sorted(sm.TERMINAL))).fetchall():
            age_progress = (now_dt - parse_iso(j["last_progress_at"])).total_seconds() if j["last_progress_at"] else 0
            if j["deadline_at"] and j["deadline_at"] < now and j["state"] in sm.LEASE_HOLDING:
                self._raise(firing, kind="job_overdue", severity="high", subject_type="job", subject_id=j["id"], repo_id=j["repo_id"],
                            condition=f"job exceeded its maximum duration ({j['deadline_at']}) while in {j['state']}",
                            reason_code="JOB_DEADLINE_EXCEEDED", last_progress=j["last_progress_note"],
                            recommended="The worker will expire it at its next checkpoint; cancel it if the worker is unresponsive.", corr=j["correlation_id"])
            if (j["state"] in sm.ACTIVE and j["lease_owner"] and j["lease_expires_at"] and j["lease_expires_at"] >= now
                    and age_progress > s.progress_stall_seconds):
                self._raise(firing, kind="progress_stalled", severity="medium", subject_type="job", subject_id=j["id"], repo_id=j["repo_id"],
                            condition=f"no progress for {int(age_progress)}s in {j['state']} (lease still being renewed)",
                            reason_code="NO_PROGRESS", last_progress=j["last_progress_note"],
                            recommended="Inspect the job; a long sandbox run is normal, otherwise cancel and replay.", corr=j["correlation_id"])
            if j["state"] == sm.QUEUED and j["queued_at"] and (now_dt - parse_iso(j["queued_at"])).total_seconds() > s.queue_age_alert_seconds and \
                    not self._queue_blocked_by_concurrency(c, j):
                self._raise(firing, kind="queue_age", severity="medium", subject_type="job", subject_id=j["id"], repo_id=j["repo_id"],
                            condition=f"queued for more than {s.queue_age_alert_seconds}s with no worker claiming it",
                            reason_code="QUEUE_AGE", last_progress=j["last_progress_note"],
                            recommended="Check that a worker is running (Settings → Local worker).", corr=j["correlation_id"])
            if j["state"] not in (sm.WAITING_FOR_APPROVAL, sm.PAUSED, sm.RETRY_WAIT, sm.QUEUED, sm.CREATED):
                cp = c.execute("SELECT MAX(created_at) AS t FROM checkpoints WHERE job_id=? AND valid=1", (j["id"],)).fetchone()["t"]
                ref = cp or j["first_started_at"]
                if ref and (now_dt - parse_iso(ref)).total_seconds() > s.stale_checkpoint_seconds:
                    self._raise(firing, kind="stale_checkpoint", severity="medium", subject_type="job", subject_id=j["id"], repo_id=j["repo_id"],
                                condition="active job has not produced a checkpoint recently", reason_code="STALE_CHECKPOINT",
                                last_progress=j["last_progress_note"], recommended="Inspect the stage; cancel and replay if it is hung.", corr=j["correlation_id"])
            lost = c.execute("SELECT COUNT(*) AS n FROM recovery_actions WHERE job_id=? AND kind='lease_reclaimed'", (j["id"],)).fetchone()["n"]
            if lost >= 3:
                self._raise(firing, kind="crash_loop", severity="high", subject_type="job", subject_id=j["id"], repo_id=j["repo_id"],
                            condition=f"worker lease expired {lost} times for this job (possible crash/restart loop)", reason_code="CRASH_LOOP",
                            last_progress=j["last_progress_note"], recommended="Cancel the job and inspect worker logs before replaying.", corr=j["correlation_id"])

        # ---- queue depth
        depth = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE state=?", (sm.QUEUED,)).fetchone()["n"]
        if depth >= s.queue_depth_alert:
            self._raise(firing, kind="queue_depth", severity="medium", subject_type="queue", subject_id="main", repo_id=None,
                        condition=f"{depth} jobs queued (threshold {s.queue_depth_alert})", reason_code="QUEUE_DEPTH", last_progress=None,
                        recommended="Add workers or review trigger volume.")
        # ---- dead-letter growth
        dlq = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE state=?", (sm.DEAD_LETTER,)).fetchone()["n"]
        if dlq >= s.dlq_alert_count:
            self._raise(firing, kind="dlq_growth", severity="high", subject_type="queue", subject_id="dead_letter", repo_id=None,
                        condition=f"{dlq} jobs in the dead-letter state (threshold {s.dlq_alert_count})", reason_code="DLQ_GROWTH", last_progress=None,
                        recommended="Open the Recovery Center, diagnose the common error and replay.")
        # ---- schedules that missed their run (scheduler not ticking)
        grace = max(60, int(s.scheduler_tick_seconds * 3))
        for sch in c.execute("SELECT * FROM schedules WHERE status='active' AND next_run_at IS NOT NULL AND next_run_at<?",
                             (iso(now_dt - timedelta(seconds=grace)),)).fetchall():
            self._raise(firing, kind="schedule_missed", severity="high", subject_type="schedule", subject_id=sch["id"], repo_id=sch["repo_id"],
                        condition=f"schedule '{sch['name']}' was due at {sch['next_run_at']} and has not fired",
                        reason_code="SCHEDULE_MISSED", last_progress=sch["last_run_at"],
                        recommended="Ensure the scheduler is running; on restart it applies the schedule's missed-run policy.")
        # ---- provider health
        for p in c.execute("SELECT * FROM provider_health WHERE consecutive_failures>=?", (s.provider_failure_alert,)).fetchall():
            self._raise(firing, kind="provider_failures", severity="high", subject_type="provider", subject_id=p["provider"], repo_id=None,
                        condition=f"{p['consecutive_failures']} consecutive failures (last: {p['last_error_code']})", reason_code="PROVIDER_FAILURES",
                        last_progress=p["last_success_at"], recommended="Check provider credentials/outage; affected jobs retry with backoff.")
        # ---- notifications
        stuck = c.execute("SELECT COUNT(*) AS n FROM notifications WHERE (status='failed' AND attempts>=5) OR (status='pending' AND created_at<?)",
                          (iso(now_dt - timedelta(seconds=s.notification_stuck_seconds)),)).fetchone()["n"]
        if stuck:
            self._raise(firing, kind="notification_failures", severity="medium", subject_type="notifications", subject_id="outbox", repo_id=None,
                        condition=f"{stuck} notification(s) failed or stuck pending", reason_code="NOTIFICATION_DELIVERY", last_progress=None,
                        recommended="Check the notification webhook configuration (Settings).")
        # ---- orphaned workspaces (safe cleanup)
        removed = self._reap_workspaces(c, now_dt)
        summary["workspaces_removed"] = len(removed)
        for jid in removed:
            self._raise(firing, kind="orphaned_workspace", severity="low", subject_type="workspace", subject_id=jid, repo_id=None,
                        condition="workspace directory of a finished or unknown job was found and removed", reason_code="ORPHANED_WORKSPACE",
                        last_progress=None, recommended="None; cleaned automatically.", auto=True, result="removed")
        # ---- worker heartbeat
        for w in c.execute("SELECT * FROM workers WHERE status='busy' AND last_heartbeat_at<?",
                           (iso(now_dt - timedelta(seconds=s.lease_seconds * 2)),)).fetchall():
            self._raise(firing, kind="worker_silent", severity="medium", subject_type="worker", subject_id=w["id"], repo_id=None,
                        condition=f"worker {w['id']} marked busy but has not reported since {w['last_heartbeat_at']}", reason_code="WORKER_SILENT",
                        last_progress=w["current_job_id"], recommended="The job lease will expire and be reclaimed automatically.")

        self._resolve_cleared(firing, {"lease_expired", "job_overdue", "progress_stalled", "queue_age", "stale_checkpoint", "crash_loop",
                                       "queue_depth", "dlq_growth", "schedule_missed", "provider_failures", "notification_failures",
                                       "orphaned_workspace", "worker_silent"})
        summary["alerts_open"] = st.db.read().execute("SELECT COUNT(*) AS n FROM alerts WHERE status='open'").fetchone()["n"]
        st.incr("watchdog_ticks")
        return summary

    @staticmethod
    def _queue_blocked_by_concurrency(c, j) -> bool:
        repo = c.execute("SELECT max_concurrent_jobs FROM repositories WHERE id=?", (j["repo_id"],)).fetchone()
        busy = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE repo_id=? AND lease_owner IS NOT NULL", (j["repo_id"],)).fetchone()["n"]
        return bool(repo and busy >= repo["max_concurrent_jobs"])

    def _reap_workspaces(self, c, now_dt) -> list[str]:
        base = Path(self.settings.workspaces_dir)
        removed = []
        if not base.is_dir():
            return removed
        for d in base.iterdir():
            if not d.is_dir() or d.is_symlink():
                continue
            row = c.execute("SELECT state, lease_owner FROM jobs WHERE id=?", (d.name,)).fetchone()
            age = time.time() - d.stat().st_mtime  # filesystem mtimes are wall-clock
            orphan = (row is None or row["state"] in sm.TERMINAL or (row["lease_owner"] is None)) and age > 60
            if orphan:
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d.name)
        return removed
