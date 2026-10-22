"""Durable job store: transitions, leases, fencing, checkpoints, retries, idempotency, audit chain.

All mutations run inside ``Database.tx()`` (BEGIN IMMEDIATE) so state, history, attempt rows and the
audit event are written atomically. In-memory state is never the source of truth for a job.
"""
from __future__ import annotations

import logging
import os
import random
import socket
from datetime import timedelta

from . import WORKFLOW_VERSION
from . import statemachine as sm
from .db import Database
from .errors import Conflict, LeaseLost, NotFound, RateLimited, ValidationError
from .redact import REDACTOR
from .retry import compute_delay, normalize_policy, recovery_hint
from .util import (Clock, canonical_json, iso, jdumps, jloads, new_correlation_id, new_id, parse_iso, sha256_hex)

JOB_JSON_COLS = ("retry_policy", "result", "error")
_UPDATABLE = {
    "outcome", "result", "error", "retry_at", "available_at", "queued_at", "lease_owner", "lease_expires_at",
    "fence", "attempt", "failed_attempts", "first_started_at", "base_tree", "base_commit", "policy_version",
    "replan_count", "cancel_requested", "pause_requested", "last_progress_at", "last_progress_note",
    "last_heartbeat_at", "priority", "allow_repair", "policy_name",
}
_DEFAULT_OUTCOME = {
    sm.FAILED: "failed", sm.DEAD_LETTER: "dead_lettered", sm.EXPIRED: "expired", sm.CANCELLED: "cancelled",
}
GENESIS = "GENESIS"


def job_from_row(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for col in JOB_JSON_COLS:
        d[col] = jloads(d.get(col))
    for col in ("allow_repair", "cancel_requested", "pause_requested"):
        d[col] = bool(d[col])
    return d


class Store:
    def __init__(self, db: Database, clock: Clock | None = None, rng: random.Random | None = None):
        self.db = db
        self.clock = clock or Clock()
        self.rng = rng or random.Random()
        self.terminal_hook = None  # callable(job_dict) invoked inside the transition transaction

    # ------------------------------------------------------------------ audit events
    def emit(self, type_: str, *, actor: str = "system", correlation_id: str | None = None, job_id: str | None = None,
             repo_id: str | None = None, schedule_id: str | None = None, data: dict | None = None) -> int:
        """Append an audit event with a hash chain link (tamper-evident, verified by verify_chain)."""
        with self.db.tx() as c:
            prev = c.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else GENESIS
            ts = iso(self.clock.now())
            payload = REDACTOR.obj(data or {})
            corr = correlation_id or new_correlation_id()
            body = canonical_json({
                "ts": ts, "type": type_, "actor": actor, "corr": corr, "job": job_id, "repo": repo_id,
                "schedule": schedule_id, "data": payload, "prev": prev_hash,
            })
            h = sha256_hex(body)
            cur = c.execute(
                "INSERT INTO events(ts, correlation_id, type, actor, job_id, repo_id, schedule_id, data, prev_hash, hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts, corr, type_, actor, job_id, repo_id, schedule_id, jdumps(payload), prev_hash, h),
            )
            return cur.lastrowid

    def verify_chain(self) -> dict:
        c = self.db.read()
        prev = GENESIS
        count = 0
        for r in c.execute("SELECT * FROM events ORDER BY id"):
            body = canonical_json({
                "ts": r["ts"], "type": r["type"], "actor": r["actor"], "corr": r["correlation_id"], "job": r["job_id"],
                "repo": r["repo_id"], "schedule": r["schedule_id"], "data": jloads(r["data"], {}), "prev": prev,
            })
            if r["prev_hash"] != prev or sha256_hex(body) != r["hash"]:
                return {"ok": False, "checked": count, "broken_at_event": r["id"]}
            prev = r["hash"]
            count += 1
        return {"ok": True, "checked": count, "broken_at_event": None}

    def incr(self, name: str, by: int = 1) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO counters(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = value + ?",
                (name, by, by),
            )

    def counter(self, name: str) -> int:
        r = self.db.read().execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
        return r["value"] if r else 0

    # ------------------------------------------------------------------ policies
    def seed_policies(self) -> None:
        defaults = {
            "default": {
                "description": "Conservative: every repair needs approval; major version jumps are never proposed.",
                "approval_required_tiers": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
                "allow_major_jump": False,
                "min_severity_for_repair": "LOW",
            },
            "lenient-low": {
                "description": "LOW-tier repairs may skip approval IF the job/repo is write-authorised; others need approval.",
                "approval_required_tiers": ["MEDIUM", "HIGH", "CRITICAL"],
                "allow_major_jump": False,
                "min_severity_for_repair": "LOW",
            },
        }
        with self.db.tx() as c:
            for name, body in defaults.items():
                if not c.execute("SELECT 1 FROM policies WHERE name=?", (name,)).fetchone():
                    c.execute(
                        "INSERT INTO policies(name, version, body, created_by, created_at) VALUES (?,?,?,?,?)",
                        (name, 1, jdumps(body), "system", iso(self.clock.now())),
                    )

    def get_policy(self, name: str, version: int | None = None) -> dict:
        c = self.db.read()
        if version is None:
            r = c.execute("SELECT * FROM policies WHERE name=? ORDER BY version DESC LIMIT 1", (name,)).fetchone()
        else:
            r = c.execute("SELECT * FROM policies WHERE name=? AND version=?", (name, version)).fetchone()
        if not r:
            raise NotFound(f"policy {name!r} not found", code="POLICY_NOT_FOUND")
        return {"name": r["name"], "version": r["version"], "body": jloads(r["body"], {}), "created_by": r["created_by"],
                "created_at": r["created_at"]}

    # ------------------------------------------------------------------ repositories
    def get_repo(self, repo_id: str) -> dict:
        r = self.db.read().execute("SELECT * FROM repositories WHERE id=?", (repo_id,)).fetchone()
        if not r:
            raise NotFound("repository not found", code="REPO_NOT_FOUND")
        return self._repo(r)

    def get_repo_by_slug(self, slug: str) -> dict | None:
        r = self.db.read().execute("SELECT * FROM repositories WHERE slug=?", (slug,)).fetchone()
        return self._repo(r) if r else None

    @staticmethod
    def _repo(r) -> dict:
        d = dict(r)
        for k in ("allow_repair", "is_demo"):
            d[k] = bool(d[k])
        return d

    # ------------------------------------------------------------------ jobs: create
    def get_job(self, job_id: str) -> dict:
        r = self.db.read().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not r:
            raise NotFound("job not found", code="JOB_NOT_FOUND")
        return job_from_row(r)

    def create_job(self, **kwargs) -> tuple[dict, bool]:
        """Create (or return the existing) job for an idempotency key. Returns (job, created)."""
        try:
            return self._create_job_tx(**kwargs)
        except RateLimited:
            self.incr("trigger_rejected_queue_cap")  # outside the rolled-back transaction
            raise

    def _create_job_tx(self, *, repo_id: str, trigger_type: str, idempotency_key: str, requested_by: str,
                   trigger_event_id: str | None = None, allow_repair: bool = False, schedule_id: str | None = None,
                   policy_name: str = "default", priority: int = 50, retry_policy: dict | None = None,
                   deadline_seconds: int | None = None, stage_timeout_seconds: int | None = None,
                   correlation_id: str | None = None, replay_of: str | None = None,
                   queue_cap: int | None = None, defaults: dict | None = None) -> tuple[dict, bool]:
        """Create (or return the existing) job for an idempotency key. Returns (job, created)."""
        corr = correlation_id or new_correlation_id()
        now = self.clock.now()
        with self.db.tx() as c:
            existing = c.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                self.incr("duplicate_trigger_suppressed")
                self.emit("trigger.duplicate_suppressed", actor=requested_by, correlation_id=corr, job_id=existing["id"],
                          repo_id=repo_id, data={"idempotency_key": idempotency_key, "trigger_type": trigger_type})
                return job_from_row(existing), False
            repo = c.execute("SELECT * FROM repositories WHERE id=?", (repo_id,)).fetchone()
            if not repo or repo["archived_at"]:
                raise NotFound("repository not found or archived", code="REPO_NOT_FOUND")
            if queue_cap:
                open_jobs = c.execute(
                    "SELECT COUNT(*) AS n FROM jobs WHERE repo_id=? AND state NOT IN (%s)"
                    % ",".join("?" * len(sm.TERMINAL)), (repo_id, *sorted(sm.TERMINAL)),
                ).fetchone()["n"]
                if open_jobs >= queue_cap:
                    raise RateLimited(f"repository has {open_jobs} open jobs (cap {queue_cap})", code="QUEUE_LIMIT")
            rp = normalize_policy(retry_policy, defaults)
            job_id = new_id("job")
            deadline = iso(now + timedelta(seconds=deadline_seconds)) if deadline_seconds else None
            c.execute(
                "INSERT INTO jobs(id, repo_id, schedule_id, trigger_type, trigger_event_id, idempotency_key, correlation_id,"
                " workflow_version, state, priority, allow_repair, requested_by, policy_name, retry_policy,"
                " stage_timeout_seconds, deadline_at, created_at, updated_at, replay_of, last_progress_at, last_progress_note)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, repo_id, schedule_id, trigger_type, trigger_event_id, idempotency_key, corr, WORKFLOW_VERSION,
                 sm.CREATED, priority, 1 if allow_repair else 0, requested_by, policy_name, jdumps(rp),
                 stage_timeout_seconds or 300, deadline, iso(now), iso(now), replay_of, iso(now), "created"),
            )
            c.execute(
                "INSERT INTO job_transitions(job_id, from_state, to_state, at, actor, source, reason_code, detail, attempt, fence, correlation_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, None, sm.CREATED, iso(now), requested_by, trigger_type, "JOB_CREATED", jdumps({}), 0, 0, corr),
            )
            self.emit("job.created", actor=requested_by, correlation_id=corr, job_id=job_id, repo_id=repo_id,
                      schedule_id=schedule_id, data={"trigger_type": trigger_type, "allow_repair": allow_repair,
                                                     "idempotency_key": idempotency_key, "replay_of": replay_of})
            self.transition(job_id, sm.QUEUED, actor=requested_by, source=trigger_type, reason_code="ENQUEUED",
                            updates={"available_at": iso(now)})
            return self.get_job(job_id), True

    # ------------------------------------------------------------------ jobs: transition
    def _check_fence(self, row, fence: int, worker_id: str | None) -> None:
        if row["fence"] != fence or row["lease_owner"] is None or (worker_id and row["lease_owner"] != worker_id):
            raise LeaseLost(f"fence mismatch for job {row['id']} (have {fence}, db {row['fence']})")

    def transition(self, job_id: str, to_state: str, *, actor: str, source: str, reason_code: str,
                   detail: dict | None = None, fence: int | None = None, worker_id: str | None = None,
                   updates: dict | None = None, expect_from=None, correlation_id: str | None = None) -> dict:
        """Validated, atomic state change. ``fence`` (with ``worker_id``) makes it a fenced worker write."""
        updates = dict(updates or {})
        bad = set(updates) - _UPDATABLE
        if bad:
            raise ValueError(f"non-updatable job columns: {sorted(bad)}")
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found", code="JOB_NOT_FOUND")
            frm = row["state"]
            if expect_from is not None and frm not in expect_from:
                raise Conflict(f"job is in {frm}, expected one of {sorted(expect_from)}", code="STATE_CHANGED")
            if fence is not None:
                self._check_fence(row, fence, worker_id)
            sm.validate(frm, to_state)
            now = iso(self.clock.now())
            corr = correlation_id or row["correlation_id"]
            sets: dict = {"state": to_state, "updated_at": now, "last_progress_at": now,
                          "last_progress_note": f"{frm} → {to_state}: {reason_code}"}
            if to_state == sm.QUEUED:
                sets["queued_at"] = now
                sets["retry_at"] = None
                sets.setdefault("available_at", now)
                # Time spent waiting for a human (approval) or paused by an operator does not consume the job's
                # duration budget; otherwise a late approval would hit JOB_DEADLINE_EXCEEDED and silently do nothing.
                if frm in (sm.WAITING_FOR_APPROVAL, sm.PAUSED) and row["deadline_at"]:
                    t = c.execute("SELECT at FROM job_transitions WHERE job_id=? AND to_state=? ORDER BY id DESC LIMIT 1",
                                  (job_id, frm)).fetchone()
                    if t:
                        waited = max(0.0, (self.clock.now() - parse_iso(t["at"])).total_seconds())
                        sets["deadline_at"] = iso(parse_iso(row["deadline_at"]) + timedelta(seconds=waited))
                        sets["last_progress_note"] += f" (deadline extended by {int(waited)}s spent in {frm})"
            if to_state in sm.TERMINAL:
                sets["finished_at"] = now
                outcome = updates.get("outcome") or row["outcome"] or _DEFAULT_OUTCOME.get(to_state)
                if outcome is None:
                    raise ValueError(f"terminal transition to {to_state} requires an outcome")
                updates["outcome"] = outcome
            lease_cleared = to_state not in sm.LEASE_HOLDING
            if lease_cleared:
                sets["lease_owner"] = None
                sets["lease_expires_at"] = None
            sets.update(updates)
            if "result" in sets and not isinstance(sets["result"], str):
                sets["result"] = jdumps(REDACTOR.obj(sets["result"]))
            if "error" in sets and not isinstance(sets["error"], str) and sets["error"] is not None:
                sets["error"] = jdumps(REDACTOR.obj(sets["error"]))
            cols = ", ".join(f"{k}=?" for k in sets)
            c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*sets.values(), job_id))
            new_fence = sets.get("fence", row["fence"])
            new_attempt = sets.get("attempt", row["attempt"])
            c.execute(
                "INSERT INTO job_transitions(job_id, from_state, to_state, at, actor, source, reason_code, detail, attempt, fence, correlation_id)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, frm, to_state, now, actor, source, reason_code, jdumps(REDACTOR.obj(detail or {})), new_attempt, new_fence, corr),
            )
            if lease_cleared and frm in sm.LEASE_HOLDING:
                err = sets.get("error")
                c.execute(
                    "UPDATE job_attempts SET ended_at=?, end_state=?, error=? WHERE job_id=? AND attempt_no=? AND ended_at IS NULL",
                    (now, to_state, err if isinstance(err, str) else None, job_id, row["attempt"]),
                )
            self.emit("job.transition", actor=actor, correlation_id=corr, job_id=job_id, repo_id=row["repo_id"],
                      schedule_id=row["schedule_id"],
                      data={"from": frm, "to": to_state, "reason_code": reason_code, "source": source,
                            "attempt": new_attempt, "detail": detail or {}})
            job = job_from_row(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if to_state in sm.TERMINAL:
                self.incr(f"jobs_terminal_{to_state.lower()}")
                if self.terminal_hook:
                    try:
                        self.terminal_hook(job)
                    except Exception:  # a notification problem must never block a state change
                        logging.getLogger("nightshift").exception("terminal hook failed for %s", job_id)
            return job

    # ------------------------------------------------------------------ leases / claim / heartbeat
    def promote_due_retries(self, actor: str = "system:requeuer") -> int:
        now = iso(self.clock.now())
        n = 0
        with self.db.tx() as c:
            rows = c.execute("SELECT id FROM jobs WHERE state=? AND retry_at IS NOT NULL AND retry_at<=?",
                             (sm.RETRY_WAIT, now)).fetchall()
            for r in rows:
                self.transition(r["id"], sm.QUEUED, actor=actor, source="system", reason_code="RETRY_DUE",
                                updates={"available_at": now})
                n += 1
        return n

    def claim_next(self, worker_id: str, lease_seconds: int) -> dict | None:
        """Atomically lease the next runnable job (priority, then age), honouring per-repo concurrency."""
        now_dt = self.clock.now()
        now = iso(now_dt)
        with self.db.tx() as c:
            self.promote_due_retries()
            cands = c.execute(
                "SELECT * FROM jobs WHERE state=? AND available_at<=? ORDER BY priority DESC, queued_at ASC LIMIT 50",
                (sm.QUEUED, now),
            ).fetchall()
            for j in cands:
                if j["deadline_at"] and j["deadline_at"] <= now:
                    self.transition(j["id"], sm.EXPIRED, actor="system:claim", source="system",
                                    reason_code="JOB_DEADLINE_EXCEEDED", updates={"outcome": "expired",
                                    "error": self._err("JOB_DEADLINE_EXCEEDED", "deadline passed while queued", "permanent")})
                    continue
                repo = c.execute("SELECT * FROM repositories WHERE id=?", (j["repo_id"],)).fetchone()
                limit = repo["max_concurrent_jobs"] if repo else 1
                busy = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE repo_id=? AND lease_owner IS NOT NULL",
                                 (j["repo_id"],)).fetchone()["n"]
                if busy >= limit:
                    continue
                attempt = j["attempt"] + 1
                fence = j["fence"] + 1
                c.execute(
                    "INSERT INTO job_attempts(job_id, attempt_no, worker_id, fence, started_at) VALUES (?,?,?,?,?)",
                    (j["id"], attempt, worker_id, fence, now),
                )
                updates = {
                    "lease_owner": worker_id, "lease_expires_at": iso(now_dt + timedelta(seconds=lease_seconds)),
                    "fence": fence, "attempt": attempt, "last_heartbeat_at": now,
                    "first_started_at": j["first_started_at"] or now,
                }
                return self.transition(j["id"], sm.VALIDATING, actor=worker_id, source="worker",
                                       reason_code="CLAIMED", detail={"attempt": attempt, "fence": fence}, updates=updates)
            return None

    def heartbeat(self, job_id: str, worker_id: str, fence: int, lease_seconds: int, note: str | None = None) -> None:
        now_dt = self.clock.now()
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found")
            self._check_fence(row, fence, worker_id)
            sets = {"lease_expires_at": iso(now_dt + timedelta(seconds=lease_seconds)), "last_heartbeat_at": iso(now_dt)}
            if note:
                sets["last_progress_at"] = iso(now_dt)
                sets["last_progress_note"] = REDACTOR.text(note)[:300]
            c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), job_id))

    def upsert_worker(self, worker_id: str, status: str, current_job: str | None = None, version: str = "") -> None:
        now = iso(self.clock.now())
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO workers(id, pid, host, started_at, last_heartbeat_at, current_job_id, status, version)"
                " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_heartbeat_at=excluded.last_heartbeat_at,"
                " current_job_id=excluded.current_job_id, status=excluded.status",
                (worker_id, os.getpid(), socket.gethostname(), now, now, current_job, status, version),
            )

    # ------------------------------------------------------------------ failure / retry
    @staticmethod
    def _err(code: str, message: str, kind: str, category: str = "infrastructure", extra: dict | None = None) -> dict:
        e = {"code": code, "message": REDACTOR.text(message)[:500], "kind": kind, "category": category,
             "recovery": recovery_hint(code)}
        if extra:
            e.update(REDACTOR.obj(extra))
        return e

    def fail_transient(self, job_id: str, *, fence: int | None, worker_id: str | None, code: str, message: str,
                       retry_after: float | None = None, actor: str = "worker", source: str = "worker",
                       bump_fence: bool = False) -> dict:
        """Record a transient failure and move to RETRY_WAIT, DEAD_LETTER or EXPIRED (bounded, never infinite)."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found")
            if fence is not None:
                self._check_fence(row, fence, worker_id)
            policy = jloads(row["retry_policy"], {})
            now_dt = self.clock.now()
            failed = row["failed_attempts"] + 1
            error = self._err(code, message, "transient", extra={"attempt": row["attempt"], "failed_attempts": failed})
            upd = {"failed_attempts": failed, "error": error}
            if bump_fence:
                upd["fence"] = row["fence"] + 1
            started = parse_iso(row["first_started_at"]) if row["first_started_at"] else now_dt
            elapsed = (now_dt - started).total_seconds()
            if row["deadline_at"] and iso(now_dt) >= row["deadline_at"]:
                error["code"] = "JOB_DEADLINE_EXCEEDED"
                error["recovery"] = recovery_hint("JOB_DEADLINE_EXCEEDED")
                upd.update(outcome="expired", error=error)
                return self.transition(job_id, sm.EXPIRED, actor=actor, source=source, reason_code="JOB_DEADLINE_EXCEEDED",
                                       detail={"last_error": code}, updates=upd)
            if failed >= int(policy.get("max_attempts", 4)):
                error["code_final"] = "RETRIES_EXHAUSTED"
                error["recovery"] = recovery_hint("RETRIES_EXHAUSTED")
                upd.update(outcome="dead_lettered", error=error)
                self.incr("dead_lettered")
                return self.transition(job_id, sm.DEAD_LETTER, actor=actor, source=source, reason_code="RETRIES_EXHAUSTED",
                                       detail={"last_error": code, "failed_attempts": failed}, updates=upd)
            if elapsed > float(policy.get("max_elapsed_seconds", 3600)):
                error["code_final"] = "RETRY_WINDOW_EXCEEDED"
                error["recovery"] = recovery_hint("RETRY_WINDOW_EXCEEDED")
                upd.update(outcome="dead_lettered", error=error)
                self.incr("dead_lettered")
                return self.transition(job_id, sm.DEAD_LETTER, actor=actor, source=source, reason_code="RETRY_WINDOW_EXCEEDED",
                                       detail={"last_error": code, "elapsed_seconds": elapsed}, updates=upd)
            delay = compute_delay(failed, policy, retry_after=retry_after, rng=self.rng)
            retry_at = iso(now_dt + timedelta(seconds=delay))
            if row["deadline_at"] and retry_at >= row["deadline_at"]:
                error["code_final"] = "DEADLINE_BEFORE_RETRY"
                upd.update(outcome="dead_lettered", error=error)
                self.incr("dead_lettered")
                return self.transition(job_id, sm.DEAD_LETTER, actor=actor, source=source, reason_code="DEADLINE_BEFORE_RETRY",
                                       detail={"last_error": code}, updates=upd)
            upd["retry_at"] = retry_at
            self.incr("retries_scheduled")
            return self.transition(job_id, sm.RETRY_WAIT, actor=actor, source=source, reason_code=code,
                                   detail={"retry_at": retry_at, "delay_seconds": round(delay, 3), "failed_attempts": failed},
                                   updates=upd)

    def fail_permanent(self, job_id: str, *, fence: int | None, worker_id: str | None, code: str, message: str,
                       category: str = "infrastructure", outcome: str = "failed", extra: dict | None = None,
                       actor: str = "worker", source: str = "worker") -> dict:
        error = self._err(code, message, "permanent", category=category, extra=extra)
        return self.transition(job_id, sm.FAILED, actor=actor, source=source, reason_code=code, fence=fence,
                               worker_id=worker_id, detail={"category": category},
                               updates={"error": error, "outcome": outcome})

    # ------------------------------------------------------------------ operator controls
    def _live_lease(self, row) -> bool:
        return bool(row["lease_owner"]) and row["lease_expires_at"] is not None and row["lease_expires_at"] > iso(self.clock.now())

    def request_cancel(self, job_id: str, actor: str, reason: str = "operator request") -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found", code="JOB_NOT_FOUND")
            if row["state"] in sm.TERMINAL:
                raise Conflict(f"job already {row['state']}", code="JOB_TERMINAL")
            if row["state"] == sm.CANCEL_REQUESTED:
                return job_from_row(row)
            c.execute("UPDATE approvals SET status='superseded' WHERE job_id=? AND status IN ('pending','approved')", (job_id,))
            job = self.transition(job_id, sm.CANCEL_REQUESTED, actor=actor, source="operator", reason_code="CANCEL_REQUESTED",
                                  detail={"reason": reason}, updates={"cancel_requested": 1})
            if not self._live_lease(row):
                job = self.transition(job_id, sm.CANCELLED, actor=actor, source="operator", reason_code="CANCELLED_NO_ACTIVE_WORKER",
                                      detail={"reason": reason}, updates={"outcome": "cancelled", "fence": row["fence"] + 1})
            return job

    def request_pause(self, job_id: str, actor: str) -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found", code="JOB_NOT_FOUND")
            st = row["state"]
            if st == sm.PAUSED:
                return job_from_row(row)
            if st in sm.ACTIVE and self._live_lease(row):
                c.execute("UPDATE jobs SET pause_requested=1, updated_at=? WHERE id=?", (iso(self.clock.now()), job_id))
                self.emit("job.pause_requested", actor=actor, job_id=job_id, repo_id=row["repo_id"],
                          correlation_id=row["correlation_id"], data={})
                return self.get_job(job_id)
            if sm.can_transition(st, sm.PAUSED) and st not in sm.ACTIVE:
                return self.transition(job_id, sm.PAUSED, actor=actor, source="operator", reason_code="PAUSED_BY_OPERATOR")
            raise Conflict(f"cannot pause a job in {st}", code="INVALID_TRANSITION")

    def resume_job(self, job_id: str, actor: str) -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found", code="JOB_NOT_FOUND")
            if row["state"] == sm.PAUSED:
                return self.transition(job_id, sm.QUEUED, actor=actor, source="operator", reason_code="RESUMED_BY_OPERATOR",
                                       updates={"pause_requested": 0, "available_at": iso(self.clock.now())})
            if row["pause_requested"]:
                c.execute("UPDATE jobs SET pause_requested=0 WHERE id=?", (job_id,))
                return self.get_job(job_id)
            raise Conflict(f"job is {row['state']}, not paused", code="INVALID_TRANSITION")

    def retry_now(self, job_id: str, actor: str) -> dict:
        """Skip the remaining backoff of a RETRY_WAIT job (does not reset the retry budget)."""
        return self.transition(job_id, sm.QUEUED, actor=actor, source="operator", reason_code="RETRY_NOW",
                               expect_from={sm.RETRY_WAIT}, updates={"available_at": iso(self.clock.now())})

    def replay_job(self, job_id: str, actor: str, *, allow_repair: bool, queue_cap: int | None = None) -> tuple[dict, bool]:
        """Create a NEW job linked to the original (history of the original is preserved)."""
        with self.db.tx() as c:
            orig = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not orig:
                raise NotFound("job not found", code="JOB_NOT_FOUND")
            if orig["state"] not in sm.TERMINAL:
                raise Conflict("only terminal jobs can be replayed; use retry/resume for others", code="JOB_NOT_TERMINAL")
            active = c.execute(
                "SELECT * FROM jobs WHERE replay_of=? AND state NOT IN (%s) ORDER BY created_at DESC LIMIT 1"
                % ",".join("?" * len(sm.TERMINAL)), (job_id, *sorted(sm.TERMINAL))).fetchone()
            if active:
                return job_from_row(active), False
            n = c.execute("SELECT COUNT(*) AS n FROM jobs WHERE replay_of=?", (job_id,)).fetchone()["n"] + 1
            new, created = self.create_job(
                repo_id=orig["repo_id"], trigger_type="replay", idempotency_key=f"replay:{job_id}:{n}", requested_by=actor,
                allow_repair=allow_repair, schedule_id=orig["schedule_id"], policy_name=orig["policy_name"],
                priority=orig["priority"], retry_policy=jloads(orig["retry_policy"], {}),
                deadline_seconds=3600, stage_timeout_seconds=orig["stage_timeout_seconds"], replay_of=job_id,
                trigger_event_id=job_id, queue_cap=queue_cap)
            self.record_recovery(job_id=job_id, kind="replay", actor=actor, source="operator", result="created",
                                 detail={"replay_job_id": new["id"]}, correlation_id=orig["correlation_id"])
            return new, created

    def record_recovery(self, *, kind: str, actor: str, source: str, result: str, job_id: str | None = None,
                        schedule_id: str | None = None, detail: dict | None = None, correlation_id: str | None = None) -> str:
        rid = new_id("rec")
        corr = correlation_id or new_correlation_id()
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO recovery_actions(id, job_id, schedule_id, kind, actor, source, result, detail, correlation_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, job_id, schedule_id, kind, actor, source, result, jdumps(REDACTOR.obj(detail or {})), corr,
                 iso(self.clock.now())),
            )
            self.emit("recovery." + kind, actor=actor, correlation_id=corr, job_id=job_id, schedule_id=schedule_id,
                      data={"result": result, "source": source, **(detail or {})})
        return rid

    # ------------------------------------------------------------------ lease reclaim (watchdog + startup)
    def reclaim_expired_leases(self, actor: str = "system:watchdog") -> list[dict]:
        """Fence out workers whose lease expired and route their jobs through bounded retry logic."""
        now = iso(self.clock.now())
        out = []
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM jobs WHERE lease_owner IS NOT NULL AND lease_expires_at<?", (now,)).fetchall()
            for row in rows:
                if row["state"] == sm.CANCEL_REQUESTED:
                    job = self.transition(row["id"], sm.CANCELLED, actor=actor, source="watchdog",
                                          reason_code="CANCELLED_AFTER_LEASE_LOSS",
                                          updates={"outcome": "cancelled", "fence": row["fence"] + 1})
                    result = "cancelled"
                else:
                    job = self.fail_transient(row["id"], fence=None, worker_id=None, code="LEASE_EXPIRED",
                                              message=f"worker {row['lease_owner']} stopped heartbeating in {row['state']}",
                                              actor=actor, source="watchdog", bump_fence=True)
                    result = job["state"]
                self.incr("lease_expiries")
                self.record_recovery(job_id=row["id"], kind="lease_reclaimed", actor=actor, source="watchdog", result=result,
                                     detail={"stale_worker": row["lease_owner"], "state_at_expiry": row["state"],
                                             "fenced_out_fence": row["fence"]}, correlation_id=row["correlation_id"])
                out.append(job)
        return out

    # ------------------------------------------------------------------ checkpoints
    def save_checkpoint(self, job_id: str, *, fence: int, worker_id: str, stage: str, data: dict,
                        base_tree: str | None, base_commit: str | None, policy_name: str | None,
                        policy_version: int | None, evidence_retrieved_at: str | None = None) -> dict:
        if stage not in sm.STAGE_ORDER:
            raise ValueError(f"unknown checkpoint stage {stage!r}")
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise NotFound("job not found")
            self._check_fence(row, fence, worker_id)
            seq = (c.execute("SELECT COALESCE(MAX(seq),0) AS m FROM checkpoints WHERE job_id=?", (job_id,)).fetchone()["m"]) + 1
            payload = jdumps(REDACTOR.obj(data))
            now = iso(self.clock.now())
            c.execute(
                "INSERT INTO checkpoints(job_id, seq, attempt, stage, data, checksum, base_tree, base_commit, policy_name,"
                " policy_version, workflow_version, evidence_retrieved_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, seq, row["attempt"], stage, payload, sha256_hex(payload), base_tree, base_commit, policy_name,
                 policy_version, row["workflow_version"], evidence_retrieved_at, now),
            )
            c.execute("UPDATE jobs SET last_progress_at=?, last_progress_note=? WHERE id=?",
                      (now, f"checkpoint saved after {stage}", job_id))
            self.emit("checkpoint.saved", actor=worker_id, correlation_id=row["correlation_id"], job_id=job_id,
                      repo_id=row["repo_id"], data={"stage": stage, "seq": seq, "attempt": row["attempt"]})
            return {"seq": seq, "stage": stage}

    def latest_valid_checkpoint(self, job_id: str) -> dict | None:
        """Newest checkpoint that is flagged valid AND whose checksum verifies (corrupt ones are invalidated)."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM checkpoints WHERE job_id=? AND valid=1 ORDER BY seq DESC", (job_id,)).fetchall()
            for r in rows:
                if sha256_hex(r["data"]) != r["checksum"]:
                    c.execute("UPDATE checkpoints SET valid=0, invalidated_reason='CHECKSUM_MISMATCH' WHERE id=?", (r["id"],))
                    self.emit("checkpoint.invalidated", job_id=job_id, data={"seq": r["seq"], "reason": "CHECKSUM_MISMATCH"})
                    continue
                d = dict(r)
                d["data"] = jloads(r["data"], {})
                return d
            return None

    def invalidate_checkpoints(self, job_id: str, *, after_stage: str | None, reason: str) -> int:
        """Mark checkpoints for stages AFTER ``after_stage`` (or all, if None) invalid. History is preserved."""
        keep = sm.STAGE_ORDER[after_stage] if after_stage else -1
        n = 0
        with self.db.tx() as c:
            for r in c.execute("SELECT id, stage FROM checkpoints WHERE job_id=? AND valid=1", (job_id,)).fetchall():
                if sm.STAGE_ORDER[r["stage"]] > keep:
                    c.execute("UPDATE checkpoints SET valid=0, invalidated_reason=? WHERE id=?", (reason, r["id"]))
                    n += 1
            if n:
                self.emit("checkpoint.invalidated_bulk", job_id=job_id, data={"after_stage": after_stage, "count": n, "reason": reason})
        return n

    # ------------------------------------------------------------------ misc reads
    def list_transitions(self, job_id: str) -> list[dict]:
        rows = self.db.read().execute("SELECT * FROM job_transitions WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = jloads(d["detail"], {})
            out.append(d)
        return out

    def add_artifact(self, job_id: str, kind: str, name: str, content: str, max_bytes: int = 512 * 1024) -> dict:
        content = REDACTOR.text(content)
        raw = content.encode("utf-8", "replace")
        truncated = False
        if len(raw) > max_bytes:
            content = raw[:max_bytes].decode("utf-8", "ignore") + "\n[... truncated by NightShift artifact size cap ...]"
            raw = content.encode("utf-8")
            truncated = True
        aid = new_id("art")
        with self.db.tx() as c:
            existing = c.execute("SELECT * FROM artifacts WHERE job_id=? AND kind=? AND name=?", (job_id, kind, name)).fetchone()
            if existing:
                c.execute("UPDATE artifacts SET content=?, sha256=?, size=?, created_at=? WHERE id=?",
                          (content, sha256_hex(raw), len(raw), iso(self.clock.now()), existing["id"]))
                aid = existing["id"]
            else:
                c.execute("INSERT INTO artifacts(id, job_id, kind, name, content, sha256, size, created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (aid, job_id, kind, name, content, sha256_hex(raw), len(raw), iso(self.clock.now())))
        return {"id": aid, "sha256": sha256_hex(raw), "size": len(raw), "truncated": truncated}

    def get_artifact_by_kind(self, job_id: str, kind: str, name: str | None = None) -> dict | None:
        q, args = "SELECT * FROM artifacts WHERE job_id=? AND kind=?", [job_id, kind]
        if name:
            q += " AND name=?"
            args.append(name)
        r = self.db.read().execute(q + " ORDER BY created_at DESC LIMIT 1", args).fetchone()
        return dict(r) if r else None

    def valid_checkpoints(self, job_id: str) -> dict:
        """Latest valid, checksum-verified checkpoint per stage, restricted to the contiguous prefix of
        STAGES (a gap means later stages cannot be trusted). Corrupt rows are invalidated with their successors."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM checkpoints WHERE job_id=? AND valid=1 ORDER BY seq", (job_id,)).fetchall()
            by_stage: dict = {}
            for r in rows:
                if sha256_hex(r["data"]) != r["checksum"]:
                    c.execute("UPDATE checkpoints SET valid=0, invalidated_reason='CHECKSUM_MISMATCH' WHERE id=?", (r["id"],))
                    self.emit("checkpoint.invalidated", job_id=job_id, data={"seq": r["seq"], "reason": "CHECKSUM_MISMATCH"})
                    # everything produced after a corrupt checkpoint is untrusted
                    for later in rows:
                        if later["seq"] > r["seq"]:
                            c.execute("UPDATE checkpoints SET valid=0, invalidated_reason='AFTER_CORRUPT_CHECKPOINT' WHERE id=?", (later["id"],))
                    break
                d = dict(r)
                d["data"] = jloads(r["data"], {})
                by_stage[r["stage"]] = d
        out = {}
        for stage in sm.STAGES:
            if stage in by_stage:
                out[stage] = by_stage[stage]
            elif stage in ("proposal", "ready", "execute", "test", "verify"):
                # write-path stages are optional only as a suffix (investigation-only jobs end after 'risk')
                break
            else:
                break
        return out

