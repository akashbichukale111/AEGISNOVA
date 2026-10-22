"""Application service: wiring + permission-checked operations + read models for the console/API.

Every entry point (HTTP, CLI, tests) goes through ``App`` so authorisation, idempotency and audit behave identically.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from collections import namedtuple
from datetime import timedelta

from . import WORKFLOW_VERSION, __version__
from . import statemachine as sm
from .config import PERMISSIONS, Settings
from .db import Database
from .errors import Conflict, Forbidden, NotFound, PayloadTooLarge, Unauthorized, ValidationError
from .governance import DevStubGovernance
from .notify import Notifier
from .providers import LocalFileProvider, OSVProvider, ProviderRunner
from .redact import REDACTOR
from .repo import resolve_repo_path, tree_hash
from .retry import recovery_hint
from .sandbox import COMMAND_LABELS, Sandbox, command_keys
from .schedule import ScheduleManager, Scheduler
from .store import Store, job_from_row
from .util import Clock, iso, jloads, new_correlation_id, new_id, parse_iso, sha256_hex
from .watchdog import Watchdog

Principal = namedtuple("Principal", "actor role")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,99}$")
SYSTEM = Principal("system", "admin")


def can(p: Principal, perm: str) -> bool:
    return p is not None and p.role in PERMISSIONS.get(perm, ())


class App:
    def __init__(self, settings: Settings, clock: Clock | None = None, rng=None, providers: list | None = None, transport=None):
        self.settings = settings
        settings.ensure_dirs()
        self.clock = clock or Clock()
        self.db = Database(settings.db_path)
        self.db.migrate_up()
        self.store = Store(self.db, self.clock, rng)
        self.store.seed_policies()
        self.local_provider = LocalFileProvider(settings.advisory_file, self.clock)
        self.local_provider_2 = LocalFileProvider(settings.advisory_file_secondary, self.clock, name="local-advisories-secondary")
        self.osv_provider = OSVProvider(settings.osv_url, self.clock) if settings.osv_enabled else None
        provs = providers if providers is not None else [self.local_provider, self.local_provider_2] + ([self.osv_provider] if self.osv_provider else [])
        self.runner = ProviderRunner(self.store, provs, self.clock)
        self.gov = DevStubGovernance(self.store)
        self.sandbox = Sandbox(settings)
        self.notifier = Notifier(self.store, settings, transport)
        self.store.terminal_hook = self._on_terminal
        self.schedules = ScheduleManager(self.store, settings)
        self.scheduler = Scheduler(self.store, settings)
        self.watchdog = Watchdog(self.store, settings, self.gov, self.notifier)
        self.started_at = iso(self.clock.now())
        self._rl: dict = {}
        self._rl_lock = threading.Lock()

    # ------------------------------------------------------------------------------------ helpers
    def _on_terminal(self, job: dict) -> None:
        self.notifier.enqueue(job["id"], "job_" + job["state"].lower(), {
            "job_id": job["id"], "repo_id": job["repo_id"], "state": job["state"], "outcome": job["outcome"],
            "correlation_id": job["correlation_id"]})

    @staticmethod
    def need(p: Principal | None, perm: str) -> None:
        if p is None:
            raise Unauthorized("authentication required")
        if not can(p, perm):
            raise Forbidden(f"role '{p.role}' lacks the '{perm}' permission", code="FORBIDDEN")

    def authenticate(self, token: str | None) -> Principal | None:
        ident = self.settings.authenticate(token)
        return Principal(*ident) if ident else None

    def rate_check(self, key: str, limit: int) -> bool:
        """Fixed-window per-minute limiter (in-process; documented limitation for multi-process deployments)."""
        window = int(self.clock.now().timestamp() // 60)
        with self._rl_lock:
            k = (key, window)
            n = self._rl.get(k, 0) + 1
            self._rl = {kk: v for kk, v in self._rl.items() if kk[1] == window}
            self._rl[k] = n
            return n <= limit

    def _q(self, sql: str, args=()) -> list[dict]:
        return [dict(r) for r in self.db.read().execute(sql, args).fetchall()]

    def _q1(self, sql: str, args=()) -> dict | None:
        r = self.db.read().execute(sql, args).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------------------------------ repositories
    def _repo_view(self, r: dict) -> dict:
        r = dict(r)
        for k in ("allow_repair", "is_demo"):
            r[k] = bool(r[k])
        return r

    def register_repo(self, p: Principal, body: dict) -> dict:
        self.need(p, "admin")
        unknown = set(body) - {"name", "slug", "rel_path", "default_branch", "policy_name", "test_command_key", "max_concurrent_jobs", "allow_repair", "is_demo"}
        if unknown:
            raise ValidationError(f"unknown field(s): {sorted(unknown)}", code="UNKNOWN_FIELD")
        name, slug, rel = str(body.get("name") or "").strip(), str(body.get("slug") or "").strip(), str(body.get("rel_path") or "").strip()
        if not 1 <= len(name) <= 80:
            raise ValidationError("name must be 1–80 characters")
        if not SLUG_RE.match(slug):
            raise ValidationError("slug must be lowercase letters, digits, '.', '_', '-', '/' (max 100)", code="INVALID_SLUG")
        try:
            resolve_repo_path(self.settings.repo_root, rel)
        except Exception as e:  # PermanentError → client-visible validation error; never echo the filesystem
            raise ValidationError("rel_path must be an existing directory inside the configured repository root", code="INVALID_REPO_PATH") from e
        policy = body.get("policy_name") or "default"
        self.store.get_policy(policy)
        tck = body.get("test_command_key") or "none"
        if tck not in command_keys():
            raise ValidationError(f"test_command_key must be one of {command_keys()}", code="INVALID_TEST_COMMAND")
        mcj = body.get("max_concurrent_jobs", 1)
        if not isinstance(mcj, int) or isinstance(mcj, bool) or not 1 <= mcj <= 5:
            raise ValidationError("max_concurrent_jobs must be 1–5")
        branch = str(body.get("default_branch") or "main")[:80]
        now = iso(self.clock.now())
        rid = new_id("rep")
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM repositories WHERE slug=?", (slug,)).fetchone():
                raise Conflict("a repository with this slug already exists", code="DUPLICATE_REPOSITORY")
            c.execute("INSERT INTO repositories(id, name, slug, rel_path, default_branch, policy_name, test_command_key, max_concurrent_jobs,"
                      " allow_repair, is_demo, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rid, name, slug, rel, branch, policy, tck, mcj, 1 if body.get("allow_repair") else 0, 1 if body.get("is_demo") else 0,
                       p.actor, now, now))
            self.store.emit("repository.registered", actor=p.actor, repo_id=rid, data={"slug": slug, "allow_repair": bool(body.get("allow_repair")),
                                                                                        "test_command_key": tck})
        return self._repo_view(self.store.get_repo(rid))

    def update_repo(self, p: Principal, repo_id: str, body: dict) -> dict:
        self.need(p, "admin")
        cur = self.store.get_repo(repo_id)
        allowed = {"name", "default_branch", "policy_name", "test_command_key", "max_concurrent_jobs", "allow_repair"}
        unknown = set(body) - allowed
        if unknown:
            raise ValidationError(f"unknown or immutable field(s): {sorted(unknown)}", code="UNKNOWN_FIELD")
        new = {**cur, **body}
        if "policy_name" in body:
            self.store.get_policy(new["policy_name"])
        if new["test_command_key"] not in command_keys():
            raise ValidationError(f"test_command_key must be one of {command_keys()}", code="INVALID_TEST_COMMAND")
        if not isinstance(new["max_concurrent_jobs"], int) or not 1 <= new["max_concurrent_jobs"] <= 5:
            raise ValidationError("max_concurrent_jobs must be 1–5")
        with self.db.tx() as c:
            c.execute("UPDATE repositories SET name=?, default_branch=?, policy_name=?, test_command_key=?, max_concurrent_jobs=?, allow_repair=?, updated_at=? WHERE id=?",
                      (str(new["name"])[:80], str(new["default_branch"])[:80], new["policy_name"], new["test_command_key"], new["max_concurrent_jobs"],
                       1 if new["allow_repair"] else 0, iso(self.clock.now()), repo_id))
            self.store.emit("repository.updated", actor=p.actor, repo_id=repo_id, data={"fields": sorted(body)})
        return self._repo_view(self.store.get_repo(repo_id))

    def archive_repo(self, p: Principal, repo_id: str) -> None:
        self.need(p, "admin")
        self.store.get_repo(repo_id)
        with self.db.tx() as c:
            c.execute("UPDATE repositories SET archived_at=? WHERE id=?", (iso(self.clock.now()), repo_id))
            c.execute("UPDATE schedules SET status='disabled', updated_at=? WHERE repo_id=? AND status IN ('active','paused')", (iso(self.clock.now()), repo_id))
            self.store.emit("repository.archived", actor=p.actor, repo_id=repo_id, data={})

    def repo_integration_check(self, repo: dict) -> dict:
        try:
            root = resolve_repo_path(self.settings.repo_root, repo["rel_path"])
            th = tree_hash(root)
            return {"status": "ok", "kind": "local-filesystem", "detail": f"{th['file_count']} files readable", "checked_at": iso(self.clock.now())}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "kind": "local-filesystem", "detail": getattr(e, "code", type(e).__name__), "checked_at": iso(self.clock.now())}

    # ------------------------------------------------------------------------------------ triggers
    def trigger(self, p: Principal, repo_id: str, *, allow_repair: bool = False, idempotency_key: str | None = None) -> tuple[dict, bool]:
        self.need(p, "operate")
        repo = self.store.get_repo(repo_id)
        if repo["archived_at"]:
            raise NotFound("repository not found or archived", code="REPO_NOT_FOUND")
        if allow_repair:
            self.need(p, "authorize_repair")
            if not repo["allow_repair"]:
                raise Forbidden("this repository is not registered as repair-capable", code="REPAIR_NOT_PERMITTED_FOR_REPO")
        if idempotency_key is not None and not re.match(r"^[A-Za-z0-9._:-]{8,80}$", idempotency_key):
            raise ValidationError("Idempotency-Key must be 8–80 chars of [A-Za-z0-9._:-]", code="INVALID_IDEMPOTENCY_KEY")
        key = f"manual:{repo_id}:{idempotency_key}" if idempotency_key else f"manual:{repo_id}:{new_id('t')}"
        return self.store.create_job(
            repo_id=repo_id, trigger_type="manual", idempotency_key=key, requested_by=p.actor, allow_repair=allow_repair,
            policy_name=repo["policy_name"], deadline_seconds=self.settings.job_max_duration_seconds,
            stage_timeout_seconds=self.settings.stage_timeout_seconds, queue_cap=self.settings.queue_cap_per_repo,
            defaults={"max_attempts": self.settings.retry_max_attempts, "base_seconds": self.settings.retry_base_seconds,
                      "max_seconds": self.settings.retry_max_seconds, "max_elapsed_seconds": self.settings.retry_max_elapsed_seconds})

    def handle_webhook(self, raw_body: bytes, headers: dict) -> dict:
        """GitHub-style webhook. Fails closed: no secret configured → disabled. Signature checked in constant time.
        Webhook-triggered jobs are ALWAYS investigation-only (never write-capable)."""
        secret = self.settings.webhook_secret
        if not secret:
            raise Forbidden("webhook endpoint is disabled (no NIGHTSHIFT_WEBHOOK_SECRET configured)", code="WEBHOOK_DISABLED")
        h = {k.lower(): v for k, v in headers.items()}
        sig = h.get("x-hub-signature-256", "")
        expect = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            self.store.incr("webhook_bad_signature")
            self.store.emit("webhook.rejected", actor="webhook", data={"reason": "bad_signature"})
            raise Unauthorized("invalid webhook signature", code="BAD_SIGNATURE")
        delivery = h.get("x-github-delivery", "")
        if not re.match(r"^[A-Za-z0-9._-]{8,100}$", delivery):
            raise ValidationError("X-GitHub-Delivery header is required", code="MISSING_DELIVERY_ID")
        event = h.get("x-github-event", "unknown")[:40]
        try:
            payload = json.loads(raw_body or b"{}")
            full_name = str(payload["repository"]["full_name"])
        except (ValueError, KeyError, TypeError):
            raise ValidationError("payload must be JSON containing repository.full_name", code="INVALID_PAYLOAD")
        repo = self.store.get_repo_by_slug(full_name.lower())
        if not repo or repo["archived_at"]:
            raise NotFound("no registered repository matches this webhook", code="REPO_NOT_FOUND")
        if event == "workflow_run" and (payload.get("workflow_run") or {}).get("conclusion") not in ("failure", "timed_out", None):
            self._webhook_record(delivery, repo["id"], None, "ignored_non_failure")
            return {"accepted": False, "reason": "workflow_run is not a failure", "delivery_id": delivery}
        with self.db.tx() as c:
            if c.execute("SELECT job_id FROM webhook_deliveries WHERE source='github' AND delivery_id=?", (delivery,)).fetchone():
                self.store.incr("duplicate_trigger_suppressed")
                row = c.execute("SELECT job_id FROM webhook_deliveries WHERE source='github' AND delivery_id=?", (delivery,)).fetchone()
                self.store.emit("trigger.duplicate_suppressed", actor="webhook", repo_id=repo["id"], job_id=row["job_id"], data={"delivery_id": delivery})
                return {"accepted": True, "duplicate": True, "job_id": row["job_id"], "delivery_id": delivery}
            job, _ = self.store.create_job(
                repo_id=repo["id"], trigger_type="webhook", idempotency_key=f"webhook:github:{delivery}", requested_by=f"webhook:github:{event}",
                trigger_event_id=delivery, allow_repair=False, policy_name=repo["policy_name"],
                deadline_seconds=self.settings.job_max_duration_seconds, stage_timeout_seconds=self.settings.stage_timeout_seconds,
                queue_cap=self.settings.queue_cap_per_repo)
            self._webhook_record(delivery, repo["id"], job["id"], "job_created")
        return {"accepted": True, "duplicate": False, "job_id": job["id"], "delivery_id": delivery}

    def _webhook_record(self, delivery, repo_id, job_id, outcome):
        with self.db.tx() as c:
            c.execute("INSERT OR IGNORE INTO webhook_deliveries(source, delivery_id, repo_id, received_at, job_id, outcome) VALUES ('github',?,?,?,?,?)",
                      (delivery, repo_id, iso(self.clock.now()), job_id, outcome))

    # ------------------------------------------------------------------------------------ operator actions
    def job_action(self, p: Principal, job_id: str, action: str, *, allow_repair: bool = False) -> dict:
        self.need(p, "operate")
        self.store.get_job(job_id)
        if action == "pause":
            return self.store.request_pause(job_id, p.actor)
        if action == "resume":
            return self.store.resume_job(job_id, p.actor)
        if action == "cancel":
            return self.store.request_cancel(job_id, p.actor)
        if action == "retry":
            job = self.store.retry_now(job_id, p.actor)
            self.store.record_recovery(job_id=job_id, kind="retry_now", actor=p.actor, source="operator", result="queued", correlation_id=job["correlation_id"])
            return job
        if action == "replay":
            if allow_repair:
                self.need(p, "authorize_repair")
            job, created = self.store.replay_job(job_id, p.actor, allow_repair=allow_repair, queue_cap=self.settings.queue_cap_per_repo)
            return {**job, "_created": created}
        raise ValidationError("action must be pause, resume, cancel, retry or replay", code="INVALID_ACTION")

    def decide_approval(self, p: Principal, approval_id: str, decision: str, note: str = "") -> dict:
        self.need(p, "approve")
        a = self.gov.decide(approval_id, approver=p.actor, decision=decision, note=note or "", enforce_sod=self.settings.require_separation_of_duties)
        job = self.store.get_job(a["job_id"])
        if job["state"] == sm.WAITING_FOR_APPROVAL:
            if decision == "approve":
                self.store.transition(job["id"], sm.QUEUED, actor=p.actor, source="governance", reason_code="APPROVED",
                                      detail={"approval_id": approval_id}, expect_from={sm.WAITING_FOR_APPROVAL})
            else:
                self.store.transition(job["id"], sm.COMPLETED_WITH_WARNINGS, actor=p.actor, source="governance", reason_code="APPROVAL_REJECTED",
                                      detail={"approval_id": approval_id}, expect_from={sm.WAITING_FOR_APPROVAL},
                                      updates={"outcome": "repair_rejected", "result": {"repair_applied": False, "note": "A human rejected the proposed repair."}})
        return a

    def revoke_approval(self, p: Principal, approval_id: str, reason: str = "") -> dict:
        self.need(p, "approve")
        a = self.gov.revoke(approval_id, actor=p.actor, reason=reason)
        job = self.store.get_job(a["job_id"])
        if job["state"] == sm.WAITING_FOR_APPROVAL:
            self.store.transition(job["id"], sm.COMPLETED_WITH_WARNINGS, actor=p.actor, source="governance", reason_code="APPROVAL_REVOKED",
                                  expect_from={sm.WAITING_FOR_APPROVAL},
                                  updates={"outcome": "repair_revoked", "result": {"repair_applied": False, "note": "Approval was revoked before execution."}})
        self.store.record_recovery(job_id=job["id"], kind="approval_revoked", actor=p.actor, source="operator", result="revoked",
                                   detail={"approval_id": approval_id, "job_state": job["state"]}, correlation_id=job["correlation_id"])
        return a

    # ------------------------------------------------------------------------------------ read models
    @staticmethod
    def _job_brief(j: dict) -> dict:
        keys = ("id", "repo_id", "state", "outcome", "trigger_type", "schedule_id", "priority", "allow_repair", "requested_by", "attempt",
                "failed_attempts", "created_at", "updated_at", "queued_at", "finished_at", "last_progress_at", "last_progress_note",
                "retry_at", "lease_owner", "lease_expires_at", "deadline_at", "replay_of", "correlation_id", "base_commit")
        out = {k: j.get(k) for k in keys}
        err = jloads(j.get("error")) if isinstance(j.get("error"), str) else j.get("error")
        out["error_code"] = (err or {}).get("code_final") or (err or {}).get("code")
        return out

    def list_jobs(self, *, repo_id=None, state=None, trigger=None, outcome=None, q=None, schedule_id=None, limit=25, offset=0) -> dict:
        limit, offset = max(1, min(int(limit), 100)), max(0, int(offset))
        where, args = [], []
        for col, val in (("repo_id", repo_id), ("state", state), ("trigger_type", trigger), ("outcome", outcome), ("schedule_id", schedule_id)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        if q:
            where.append("(id LIKE ? OR correlation_id LIKE ? OR requested_by LIKE ?)")
            args += [f"%{q[:60]}%"] * 3
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = self._q1(f"SELECT COUNT(*) AS n FROM jobs{w}", args)["n"]
        rows = self._q(f"SELECT * FROM jobs{w} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        return {"items": [self._job_brief(job_from_row(r)) for r in rows], "total": total, "limit": limit, "offset": offset,
                "next_offset": offset + limit if offset + limit < total else None}

    def explain(self, job: dict, approvals: list[dict]) -> dict:
        """Deterministic, rule-based explanation (no model involved)."""
        st, err = job["state"], job.get("error") or {}
        now = self.clock.now()
        age = int((now - parse_iso(job["last_progress_at"])).total_seconds()) if job.get("last_progress_at") else None
        if st == sm.WAITING_FOR_APPROVAL:
            a = next((x for x in approvals if x["status"] == "pending"), None)
            text = ("Waiting for a human decision — this is expected, not stalled."
                    + (f" Approval {a['id']} expires {a['expires_at']}." if a else ""))
            nxt = "An approver reviews the scoped proposal in the Approvals panel."
        elif st == sm.RETRY_WAIT:
            text = f"Transient failure ({err.get('code')}); retry {job['failed_attempts']}/{job['retry_policy'].get('max_attempts')} scheduled for {job['retry_at']}."
            nxt = "Wait, or use 'Retry now' to skip the remaining backoff (budget is not reset)."
        elif st == sm.PAUSED:
            text, nxt = "Paused by an operator.", "Resume to re-queue from the last valid checkpoint."
        elif st == sm.QUEUED:
            text, nxt = "Queued; a worker will claim it (per-repository concurrency applies).", "None needed."
        elif st in sm.ACTIVE:
            expired = job.get("lease_expires_at") and job["lease_expires_at"] < iso(now)
            text = f"Running stage {st}; last progress {age}s ago." + (" The worker lease has EXPIRED; the watchdog will reclaim it." if expired else "")
            nxt = "None needed." if not expired else "The job resumes from its last valid checkpoint automatically."
        elif st == sm.CANCEL_REQUESTED:
            text, nxt = "Cancellation requested; the worker is winding down.", "None needed."
        elif st in sm.TERMINAL:
            o = job.get("outcome")
            text = {
                "repair_verified": "A repair patch was produced and passed regression tests and independent verification. It has NOT been applied or merged.",
                "investigation_only": "Investigation complete. Findings were recorded; no repair was performed or verified.",
                "no_findings": "Investigation complete. No known-vulnerable dependencies were found against the available evidence.",
                "repair_blocked": f"A safety gate blocked the repair ({err.get('code')}). Nothing was changed.",
                "repair_rejected": "A human rejected the proposed repair. Nothing was changed.",
                "repair_revoked": "The approval was revoked. Nothing was changed.",
                "approval_expired": "The approval expired before the repair could run. Nothing was changed.",
                "dead_lettered": f"Retries exhausted ({err.get('code_final') or err.get('code')}). Operator attention required.",
                "expired": f"The job expired ({err.get('code')}).", "cancelled": "Cancelled.", "failed": f"Failed permanently ({err.get('code')}).",
            }.get(o, f"Finished as {st}.")
            nxt = err.get("recovery") or ("Replay creates a new linked job." if st != sm.COMPLETED else "None needed.")
        else:
            text, nxt = f"State {st}.", ""
        return {"summary": text, "next_step": nxt, "method": "deterministic rules (no model used)"}

    def resume_eligibility(self, job: dict) -> dict:
        st = job["state"]
        cp = self.store.valid_checkpoints(job["id"])
        last = list(cp)[-1] if cp else None
        base = {"has_valid_checkpoint": bool(cp), "last_checkpoint_stage": last}
        if st == sm.RETRY_WAIT:
            return {**base, "eligible": True, "how": "retry", "note": "Will resume from the last valid checkpoint; all preconditions are re-verified first."}
        if st == sm.PAUSED:
            return {**base, "eligible": True, "how": "resume", "note": "Resumes from the last valid checkpoint after re-verifying base commit, policy and evidence."}
        if st in (sm.FAILED, sm.DEAD_LETTER, sm.EXPIRED):
            return {**base, "eligible": True, "how": "replay", "note": "Creates a NEW linked job; the original history is preserved."}
        if st in sm.TERMINAL:
            return {**base, "eligible": True, "how": "replay", "note": "Re-run for a fresh result (new linked job)."}
        return {**base, "eligible": False, "how": None, "note": "Job is in progress or waiting."}

    def allowed_actions(self, p: Principal | None, job: dict, approvals: list[dict]) -> list[dict]:
        def act(name, ok_state, perm, reason_state):
            if p is None or not can(p, perm):
                return {"action": name, "enabled": False, "reason": f"requires the '{perm}' permission"}
            return {"action": name, "enabled": ok_state, "reason": None if ok_state else reason_state}
        st = job["state"]
        out = [
            act("pause", st in sm.ACTIVE or st in (sm.QUEUED, sm.RETRY_WAIT, sm.WAITING_FOR_APPROVAL), "operate", f"cannot pause a job in {st}"),
            act("resume", st == sm.PAUSED, "operate", "job is not paused"),
            act("cancel", st not in sm.TERMINAL and st != sm.CANCEL_REQUESTED, "operate", "job is already finished or cancelling"),
            act("retry", st == sm.RETRY_WAIT, "operate", "only jobs in RETRY_WAIT can skip their backoff"),
            act("replay", st in sm.TERMINAL, "operate", "only finished jobs can be replayed"),
        ]
        pend = next((a for a in approvals if a["status"] == "pending"), None)
        for name in ("approve", "reject"):
            e = act(name, bool(pend) and st == sm.WAITING_FOR_APPROVAL, "approve", "no pending approval")
            if e["enabled"] and self.settings.require_separation_of_duties and p.actor in (pend["requested_by"], job["requested_by"]):
                e = {"action": name, "enabled": False, "reason": "separation of duties: the requester cannot decide their own request"}
            out.append(e)
        live = next((a for a in approvals if a["status"] in ("pending", "approved")), None)
        out.append(act("revoke", bool(live), "approve", "no live approval to revoke"))
        return out

    def job_detail(self, job_id: str, p: Principal | None = None) -> dict:
        job = self.store.get_job(job_id)
        transitions = self.store.list_transitions(job_id)
        approvals = [self.gov._row(r) for r in self.db.read().execute("SELECT * FROM approvals WHERE job_id=? ORDER BY requested_at", (job_id,))]
        cps = self._q("SELECT id, seq, attempt, stage, checksum, base_tree, base_commit, policy_name, policy_version, workflow_version, evidence_retrieved_at, valid, invalidated_reason, created_at FROM checkpoints WHERE job_id=? ORDER BY seq", (job_id,))
        now = self.clock.now()
        durations: dict = {}
        for i, t in enumerate(transitions):
            end = parse_iso(transitions[i + 1]["at"]) if i + 1 < len(transitions) else (parse_iso(job["finished_at"]) if job["finished_at"] else now)
            durations.setdefault(t["to_state"], 0.0)
            durations[t["to_state"]] += max(0.0, (end - parse_iso(t["at"])).total_seconds())
        lease_live = bool(job["lease_owner"]) and bool(job["lease_expires_at"]) and job["lease_expires_at"] > iso(now)
        risk = self._q("SELECT * FROM risk_assessments WHERE job_id=? ORDER BY created_at DESC", (job_id,))
        for r in risk:
            r["reason_codes"], r["detail"] = jloads(r["reason_codes"], []), jloads(r["detail"], {})
        findings = self._q("SELECT f.* FROM findings f JOIN finding_observations o ON o.finding_id=f.id WHERE o.job_id=? ORDER BY f.risk_score DESC", (job_id,))
        findings = [self._finding_view(f) for f in findings]
        return {
            "job": job, "brief": self._job_brief(job), "transitions": transitions,
            "attempts": self._q("SELECT * FROM job_attempts WHERE job_id=? ORDER BY attempt_no", (job_id,)),
            "checkpoints": cps, "resume": self.resume_eligibility(job),
            "lease": {"owner": job["lease_owner"], "expires_at": job["lease_expires_at"], "live": lease_live, "fence": job["fence"],
                      "last_heartbeat_at": job["last_heartbeat_at"]},
            "stage_durations_seconds": {k: round(v, 3) for k, v in durations.items()},
            "approvals": approvals, "risk_assessments": risk, "findings": findings,
            "evidence": self._q("SELECT id, finding_id, source, source_mode, advisory_id, package, url, retrieved_at, content_hash, summary FROM evidence WHERE job_id=? ORDER BY advisory_id", (job_id,)),
            "artifacts": self._q("SELECT id, kind, name, sha256, size, created_at FROM artifacts WHERE job_id=? ORDER BY created_at", (job_id,)),
            "notifications": self._q("SELECT id, event_type, channel, status, attempts, last_error, created_at, updated_at FROM notifications WHERE job_id=? ORDER BY created_at", (job_id,)),
            "explanation": self.explain(job, approvals), "actions": self.allowed_actions(p, job, approvals),
            "replays": self._q("SELECT id, state, outcome, created_at FROM jobs WHERE replay_of=? ORDER BY created_at", (job_id,)),
            "server_time": iso(now),
        }

    def artifact(self, artifact_id: str) -> dict:
        a = self._q1("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if not a:
            raise NotFound("artifact not found", code="ARTIFACT_NOT_FOUND")
        return a

    # ---- findings
    @staticmethod
    def _finding_view(f: dict) -> dict:
        for k in ("manifest_paths", "advisory_ids", "affected_ranges", "fixed_candidates", "reason_codes", "limitations"):
            f[k] = jloads(f.get(k), [])
        f["requires_approval"] = bool(f["requires_approval"])
        return f

    def list_findings(self, *, repo_id=None, severity=None, status=None, ecosystem=None, q=None, limit=25, offset=0) -> dict:
        limit, offset = max(1, min(int(limit), 100)), max(0, int(offset))
        where, args = [], []
        for col, val in (("repo_id", repo_id), ("severity", severity), ("status", status), ("ecosystem", ecosystem)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        if q:
            where.append("(package LIKE ? OR advisory_ids LIKE ?)")
            args += [f"%{q[:60]}%"] * 2
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = self._q1(f"SELECT COUNT(*) AS n FROM findings{w}", args)["n"]
        rows = self._q(f"SELECT * FROM findings{w} ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END, package LIMIT ? OFFSET ?", (*args, limit, offset))
        return {"items": [self._finding_view(r) for r in rows], "total": total, "limit": limit, "offset": offset,
                "next_offset": offset + limit if offset + limit < total else None}

    def finding_detail(self, finding_id: str) -> dict:
        f = self._q1("SELECT * FROM findings WHERE id=?", (finding_id,))
        if not f:
            raise NotFound("finding not found", code="FINDING_NOT_FOUND")
        f = self._finding_view(f)
        ev = self._q("SELECT * FROM evidence WHERE finding_id=? ORDER BY retrieved_at DESC, advisory_id", (finding_id,))
        for e in ev:
            e["summary"] = jloads(e["summary"], {})
        # confirmed facts vs hypotheses (kept separate on purpose)
        facts = [f"Installed version {f['installed_version']} of {f['package']} ({f['ecosystem']}) is declared in {', '.join(f['manifest_paths'])}.",
                 f"Advisory evidence matches this version: {', '.join(f['advisory_ids'])}."]
        hyp = []
        if f["relationship"] == "unknown":
            hyp.append("Direct vs transitive relationship is unknown (requirements files do not distinguish them).")
        if f["selected_fix"]:
            hyp.append(f"{f['selected_fix']} clears all known advisories (derived from advisory ranges; compatibility with your code is NOT verified until tests run).")
        if "FIX_MAJOR_JUMP" in f["reason_codes"]:
            hyp.append("The fix crosses a major version: breaking changes are plausible; policy blocks automated repair by default.")
        if f["evidence_status"] == "conflicting":
            facts.append("Evidence sources DISAGREE on affectedness or fix version — a human must reconcile before action.")
        if f["evidence_status"] == "stale":
            facts.append("At least one evidence record is older than the freshness limit; it must be refreshed before any repair.")
        if not f["selected_fix"]:
            facts.append("No fix version is established by the evidence. NightShift will not invent one.")
        prior = self._q("SELECT * FROM risk_assessments WHERE job_id=? ORDER BY created_at DESC LIMIT 1", (f["last_job_id"],))
        plan = None
        if prior:
            detail = jloads(prior[0]["detail"], {})
            pf = next((x for x in detail.get("per_finding", []) if x["finding_id"] == finding_id), None)
            if pf:
                plan = {"eligible_for_automated_repair": pf["eligible"], "blockers": pf["repair_blockers"], "score": pf["score"], "tier": pf["tier"],
                        "approval_required": detail.get("approval_required") if pf["eligible"] else None,
                        "requirements": (["Write-authorised job on a repair-capable repository", "Scoped approval (repository, base commit, paths, diff hash, policy, expiry)",
                                          "Regression tests pass in an isolated workspace", "Independent verification agrees"] if pf["eligible"] else []),
                        "policy": detail.get("policy")}
        obs = self._q("SELECT observed_at, installed_version, severity, risk_score, evidence_status, job_id FROM finding_observations WHERE finding_id=? ORDER BY observed_at DESC LIMIT 20", (finding_id,))
        return {"finding": f, "evidence": ev, "facts": facts, "hypotheses": hyp, "repair_plan": plan, "observations": obs}

    # ---- repositories (fleet)
    def fleet(self) -> list[dict]:
        out = []
        week = iso(self.clock.now() - timedelta(days=7))
        for r in self._q("SELECT * FROM repositories WHERE archived_at IS NULL ORDER BY name"):
            r = self._repo_view(r)
            rid = r["id"]
            snap = self._q1("SELECT id, tree_hash, commit_sha, file_count, taken_at, job_id FROM repo_snapshots WHERE repo_id=? ORDER BY taken_at DESC LIMIT 1", (rid,))
            last_ok = self._q1("SELECT id, finished_at, outcome, state FROM jobs WHERE repo_id=? AND state IN ('COMPLETED','COMPLETED_WITH_WARNINGS') ORDER BY finished_at DESC LIMIT 1", (rid,))
            sev = {x["severity"]: x["n"] for x in self._q("SELECT severity, COUNT(*) AS n FROM findings WHERE repo_id=? AND status='open' GROUP BY severity", (rid,))}
            openj = self._q1("SELECT COUNT(*) AS n FROM jobs WHERE repo_id=? AND state NOT IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','CANCELLED','EXPIRED','DEAD_LETTER')", (rid,))["n"]
            fails = self._q1("SELECT COUNT(*) AS n FROM jobs WHERE repo_id=? AND state IN ('FAILED','DEAD_LETTER','EXPIRED') AND finished_at>?", (rid, week))["n"]
            trend = self._q("SELECT job_id, MAX(risk_score) AS max_risk, MAX(observed_at) AS at FROM finding_observations WHERE repo_id=? AND risk_score IS NOT NULL GROUP BY job_id ORDER BY at", (rid,))
            scheds = self._q("SELECT id, name, status, next_run_at, last_run_at, last_status FROM schedules WHERE repo_id=? AND status!='deleted' ORDER BY name", (rid,))
            r.update({"latest_snapshot": snap, "last_successful_scan": last_ok, "open_findings_by_severity": sev, "open_findings": sum(sev.values()),
                      "open_jobs": openj, "recent_failures_7d": fails, "risk_trend": trend if len(trend) >= 3 else None,
                      "risk_trend_note": None if len(trend) >= 3 else f"{len(trend)} data point(s); a trend needs at least 3 completed scans",
                      "schedules": scheds, "integration": self.repo_integration_check(r),
                      "github": {"status": "not_connected", "detail": "GitHub integration is not implemented in the standalone build"},
                      "policy": self.store.get_policy(r["policy_name"])})
            out.append(r)
        return out

    # ---- overview
    def overview(self, p: Principal | None = None) -> dict:
        now = self.clock.now()
        st = self.store
        counts = {r["state"]: r["n"] for r in self._q("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state")}
        active = self._q("SELECT * FROM jobs WHERE state IN (%s) ORDER BY updated_at DESC LIMIT 20" % ",".join("?" * len(sm.LEASE_HOLDING)), tuple(sorted(sm.LEASE_HOLDING)))
        queued = self._q("SELECT queued_at FROM jobs WHERE state='QUEUED' ORDER BY queued_at")
        oldest = (now - parse_iso(queued[0]["queued_at"])).total_seconds() if queued else 0
        recent = self._q("SELECT * FROM jobs WHERE state IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','DEAD_LETTER','EXPIRED','CANCELLED') ORDER BY finished_at DESC LIMIT 12")
        waiting = self._q("SELECT * FROM jobs WHERE state IN ('WAITING_FOR_APPROVAL','PAUSED','RETRY_WAIT') ORDER BY updated_at DESC LIMIT 15")
        sched = self._q("SELECT s.id, s.name, s.next_run_at, s.last_run_at, s.last_status, s.repo_id, s.timezone, s.allow_repair FROM schedules s WHERE s.status='active' AND s.next_run_at IS NOT NULL ORDER BY s.next_run_at LIMIT 8")
        recovered = self._q1("SELECT COUNT(*) AS n FROM recovery_actions WHERE kind IN ('lease_reclaimed','retry_now','replay') AND created_at>?", (iso(now - timedelta(days=1)),))["n"]
        sevs = {x["severity"]: x["n"] for x in self._q("SELECT severity, COUNT(*) AS n FROM findings WHERE status='open' GROUP BY severity")}
        appr = self._q1("SELECT SUM(status='pending') AS pending, SUM(status='expired') AS expired FROM approvals")
        fresh = self._q("SELECT repo_id, MIN(retrieved_at) AS oldest, MAX(retrieved_at) AS newest FROM evidence GROUP BY repo_id")
        workers = self._q("SELECT id, status, last_heartbeat_at, current_job_id, started_at FROM workers ORDER BY last_heartbeat_at DESC LIMIT 10")
        for w in workers:
            w["heartbeat_age_seconds"] = int((now - parse_iso(w["last_heartbeat_at"])).total_seconds())
            w["healthy"] = w["heartbeat_age_seconds"] <= max(10, self.settings.lease_seconds)
        alerts = self._q("SELECT * FROM alerts WHERE status='open' ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, detected_at DESC LIMIT 12")
        providers = self.provider_health()
        degraded = bool(alerts) or any(x["status"] in ("down", "degraded") for x in providers)
        timeline = self._q("SELECT id, ts, type, actor, job_id, repo_id, schedule_id, data FROM events ORDER BY id DESC LIMIT 25")
        for e in timeline:
            e["data"] = jloads(e["data"], {})
        return {
            "generated_at": iso(now), "version": __version__,
            "mode": {"execution": self.settings.mode, "label": "Local mode (SQLite + in-process worker)" if self.settings.mode == "local" else self.settings.mode,
                     "status": "degraded" if degraded else "ok", "aws": {"status": "not_configured", "detail": "AWS adapters are design-only in this standalone build"}},
            "counts_by_state": counts, "jobs_total": sum(counts.values()),
            "active_jobs": [self._job_brief(job_from_row(j)) for j in active],
            "waiting_jobs": [self._job_brief(job_from_row(j)) for j in waiting],
            "recent_jobs": [self._job_brief(job_from_row(j)) for j in recent],
            "upcoming_schedules": sched,
            "queue": {"depth": counts.get("QUEUED", 0), "oldest_age_seconds": int(oldest), "retry_wait": counts.get("RETRY_WAIT", 0)},
            "recovery_24h": recovered, "dead_letter": counts.get("DEAD_LETTER", 0),
            "findings_by_severity": sevs,
            "approvals": {"pending": appr["pending"] or 0, "expired": appr["expired"] or 0},
            "evidence_freshness": fresh, "workers": workers, "alerts": alerts, "providers": providers,
            "timeline": timeline, "fleet_size": self._q1("SELECT COUNT(*) AS n FROM repositories WHERE archived_at IS NULL")["n"],
        }

    # ---- recovery center
    def recovery(self) -> dict:
        now = self.clock.now()
        nowiso = iso(now)
        stuck = self._q("SELECT * FROM jobs WHERE state IN (%s) AND (lease_expires_at<? OR last_progress_at<?) ORDER BY updated_at" % ",".join("?" * len(sm.LEASE_HOLDING)),
                        (*sorted(sm.LEASE_HOLDING), nowiso, iso(now - timedelta(seconds=self.settings.progress_stall_seconds))))
        expired_leases = [j for j in stuck if j["lease_expires_at"] and j["lease_expires_at"] < nowiso]
        retry_q = self._q("SELECT * FROM jobs WHERE state='RETRY_WAIT' ORDER BY retry_at")
        dlq = self._q("SELECT * FROM jobs WHERE state IN ('DEAD_LETTER','FAILED','EXPIRED') ORDER BY finished_at DESC LIMIT 50")
        bad_sched = self._q("SELECT s.*, r.name AS repo_name FROM schedules s JOIN repositories r ON r.id=s.repo_id WHERE s.status!='deleted' AND (s.last_status IN ('error','missed_skipped','skipped_concurrency') OR (s.status='active' AND s.next_run_at<?)) ORDER BY s.updated_at DESC", (iso(now - timedelta(seconds=60)),))
        exp_appr = self._q("SELECT a.*, j.state AS job_state FROM approvals a JOIN jobs j ON j.id=a.job_id WHERE a.status='expired' ORDER BY a.expires_at DESC LIMIT 20")
        for a in exp_appr:
            a["scope"] = jloads(a["scope"], {})
        def rec(j):
            b = self._job_brief(job_from_row(j))
            code = b["error_code"]
            b["recommendation"] = recovery_hint(code) if code else "Inspect the job."
            b["resume"] = self.resume_eligibility(job_from_row(j))
            return b
        history = self._q("SELECT * FROM recovery_actions ORDER BY created_at DESC LIMIT 40")
        for h in history:
            h["detail"] = jloads(h["detail"], {})
        return {"generated_at": nowiso, "stuck_jobs": [rec(j) for j in stuck], "expired_leases": [rec(j) for j in expired_leases],
                "retry_queue": [rec(j) for j in retry_q], "dead_letter": [rec(j) for j in dlq],
                "failed_schedules": bad_sched, "provider_outages": [x for x in self.provider_health() if x["status"] in ("down", "degraded")],
                "expired_approvals": exp_appr, "alerts": self._q("SELECT * FROM alerts ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, detected_at DESC LIMIT 60"),
                "history": history}

    # ---- audit
    def audit(self, *, repo_id=None, job_id=None, type_prefix=None, actor=None, since=None, until=None, state=None, limit=50, offset=0) -> dict:
        limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
        where, args = [], []
        if repo_id:
            where.append("repo_id=?"); args.append(repo_id)
        if job_id:
            where.append("job_id=?"); args.append(job_id)
        if type_prefix:
            where.append("type LIKE ?"); args.append(type_prefix.replace("%", "")[:60] + "%")
        if actor:
            where.append("actor LIKE ?"); args.append("%" + actor.replace("%", "")[:60] + "%")
        if since:
            where.append("ts>=?"); args.append(since)
        if until:
            where.append("ts<=?"); args.append(until)
        if state:
            where.append("job_id IN (SELECT id FROM jobs WHERE state=?)"); args.append(state)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        total = self._q1(f"SELECT COUNT(*) AS n FROM events{w}", args)["n"]
        rows = self._q(f"SELECT * FROM events{w} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
        for r in rows:
            r["data"] = jloads(r["data"], {})
        return {"items": rows, "total": total, "limit": limit, "offset": offset, "next_offset": offset + limit if offset + limit < total else None,
                "chain": self.store.verify_chain()}

    def audit_extras(self) -> dict:
        proofs = self._q("SELECT a.id, a.job_id, a.name, a.sha256, a.created_at, j.repo_id FROM artifacts a JOIN jobs j ON j.id=a.job_id WHERE a.kind='repair_proof' ORDER BY a.created_at DESC LIMIT 30")
        policy = self._q("SELECT job_id, policy_name, policy_version, score, tier, repair_decision, created_at FROM risk_assessments ORDER BY created_at DESC LIMIT 40")
        approvals = self._q("SELECT id, job_id, repo_id, provider, status, requested_by, requested_at, expires_at, decided_by, decided_at, revoked_by, revoked_at, revoke_reason, scope_hash FROM approvals ORDER BY requested_at DESC LIMIT 40")
        prov = self._q("SELECT provider, operation, ok, latency_ms, error_code, at FROM provider_calls ORDER BY id DESC LIMIT 40")
        notif = self._q("SELECT id, job_id, event_type, channel, status, attempts, last_error, created_at FROM notifications ORDER BY created_at DESC LIMIT 40")
        return {"repair_proofs": proofs, "policy_decisions": policy, "approvals": approvals, "provider_usage": prov, "notifications": notif,
                "model_usage": {"status": "none", "detail": "No language model is used in the standalone build; all decisions are deterministic."}}

    # ---- providers / settings
    def provider_health(self) -> list[dict]:
        rows = {r["provider"]: r for r in self.runner.health()}
        out = []
        local = self.local_provider
        r = rows.get(local.name)
        out.append({"provider": local.name, "label": "Advisory evidence — local snapshot file", "mode": local.mode,
                    "status": (r["status"] if r else ("unverified" if local.configured() else "unconfigured")),
                    "configured": local.configured(), "last_check_at": r and r["last_check_at"], "last_success_at": r and r["last_success_at"],
                    "consecutive_failures": r["consecutive_failures"] if r else 0, "last_error_code": r and r["last_error_code"],
                    "detail": local.describe() if local.configured() else "advisory snapshot file not found"})
        o = rows.get("osv")
        out.append({"provider": "osv", "label": "Advisory evidence — OSV (live API)", "mode": "live" if self.osv_provider else "disabled",
                    "status": (o["status"] if o else ("unverified" if self.osv_provider else "unconfigured")), "configured": bool(self.osv_provider),
                    "last_check_at": o and o["last_check_at"], "last_success_at": o and o["last_success_at"],
                    "consecutive_failures": o["consecutive_failures"] if o else 0, "last_error_code": o and o["last_error_code"],
                    "detail": "enabled via NIGHTSHIFT_OSV_ENABLED=1" if self.osv_provider else "disabled (set NIGHTSHIFT_OSV_ENABLED=1; requires outbound HTTPS)"})
        if self.local_provider_2.configured():
            r2 = rows.get(self.local_provider_2.name)
            out.insert(1, {"provider": self.local_provider_2.name, "label": "Advisory evidence — secondary local snapshot", "mode": "local-file",
                           "status": r2["status"] if r2 else "unverified", "configured": True, "last_check_at": r2 and r2["last_check_at"],
                           "last_success_at": r2 and r2["last_success_at"], "consecutive_failures": r2["consecutive_failures"] if r2 else 0,
                           "last_error_code": r2 and r2["last_error_code"], "detail": self.local_provider_2.describe()})
        return out

    def settings_view(self, p: Principal | None = None) -> dict:
        now = self.clock.now()
        sb = self.sandbox.preflight()
        workers = self._q("SELECT * FROM workers ORDER BY last_heartbeat_at DESC")
        healthy = [w for w in workers if (now - parse_iso(w["last_heartbeat_at"])).total_seconds() <= max(10, self.settings.lease_seconds)]
        components = [
            {"id": "persistence", "label": "Persistence & queue", "status": "ok", "mode": "SQLite (WAL), durable queue in the jobs table",
             "detail": f"migrations applied: {', '.join(self.db.applied_versions())}"},
            {"id": "worker", "label": "Local worker", "status": "ok" if healthy else "unavailable", "mode": "in-process threads",
             "detail": f"{len(healthy)} healthy of {len(workers)} known worker(s)"},
            {"id": "sandbox", "label": "Execution sandbox", "status": "ok" if sb["available"] else "blocked", "mode": sb["backend"],
             "detail": (sb["reason"] or "network isolated via unshare; rlimits; NO filesystem confinement") + " — repairs fail closed when unavailable"},
            {"id": "governance", "label": "Governance (UNWIND)", "status": "stub", "mode": DevStubGovernance.mode,
             "detail": "UNWIND contract not available to this build; a narrow adapter interface + development stub is used"},
            {"id": "verifier", "label": "Independent verifier", "status": "built_in", "mode": "built-in deterministic verifier",
             "detail": "AEGISNOVA Independent Repair Assurance is not connected"},
            {"id": "github", "label": "GitHub integration", "status": "not_implemented", "mode": "none",
             "detail": "Webhook intake is implemented (HMAC-verified). No GitHub API client: no PRs are created."},
            {"id": "webhook", "label": "GitHub webhook intake", "status": "configured" if self.settings.webhook_secret else "disabled", "mode": "HMAC-SHA256",
             "detail": "secret configured (value hidden)" if self.settings.webhook_secret else "disabled: NIGHTSHIFT_WEBHOOK_SECRET not set"},
            {"id": "tavily", "label": "Tavily research", "status": "not_implemented", "mode": "none", "detail": "not implemented in the standalone build"},
            {"id": "model", "label": "Model provider (NVIDIA via Nebius Token Factory)", "status": "not_implemented", "mode": "none",
             "detail": "no model is used; scheduling, risk, approval and retries are deterministic"},
            {"id": "aws", "label": "AWS scheduler / orchestration", "status": "not_configured", "mode": "none",
             "detail": "EventBridge Scheduler / Step Functions / SQS adapters are documented, not built or deployed"},
            {"id": "notifications", "label": "Notification channels", "status": "ok", "mode": ", ".join(self.notifier.channels()),
             "detail": "'local' records to the outbox (NOT external delivery); webhook " + ("configured" if self.settings.notify_webhook_url else "not configured") + "; email/SMS/WhatsApp not implemented"},
            {"id": "auth", "label": "Authentication & access policy", "status": "ok" if self.settings.tokens else "blocked", "mode": "bearer tokens (hashed in memory)",
             "detail": f"{len(self.settings.tokens)} token(s) configured; roles viewer/operator/approver/admin; separation of duties {'on' if self.settings.require_separation_of_duties else 'OFF'}"},
        ]
        return {"config": self.settings.public_view(), "components": components, "providers": self.provider_health(), "sandbox": sb,
                "command_catalogue": COMMAND_LABELS, "policies": [self.store.get_policy(n) for n in ("default", "lenient-low")],
                "workflow_version": WORKFLOW_VERSION, "started_at": self.started_at, "generated_at": iso(now)}

    def check_provider(self, p: Principal, name: str) -> dict:
        self.need(p, "operate")
        prov = next((x for x in self.runner.providers if x.name == name), None)
        if prov is None:
            raise NotFound("provider is not configured", code="PROVIDER_NOT_CONFIGURED")
        return self.runner.check(prov)

    # ---- metrics
    def metrics(self) -> dict:
        st = self.store
        now = self.clock.now()
        c = {r["name"]: r["value"] for r in self._q("SELECT name, value FROM counters")}
        durations: dict = {}
        for j in self._q("SELECT id FROM jobs WHERE state IN ('COMPLETED','COMPLETED_WITH_WARNINGS') ORDER BY finished_at DESC LIMIT 200"):
            tr = st.list_transitions(j["id"])
            for i, t in enumerate(tr[:-1]):
                durations.setdefault(t["to_state"], []).append((parse_iso(tr[i + 1]["at"]) - parse_iso(t["at"])).total_seconds())
        stage = {k: {"count": len(v), "avg_seconds": round(sum(v) / len(v), 3), "max_seconds": round(max(v), 3)} for k, v in durations.items() if k in sm.ACTIVE}
        wait = self._q("SELECT j.queued_at AS q, a.started_at AS s FROM job_attempts a JOIN jobs j ON j.id=a.job_id WHERE a.attempt_no=1 AND j.queued_at IS NOT NULL ORDER BY a.id DESC LIMIT 200")
        waits = [(parse_iso(w["s"]) - parse_iso(w["q"])).total_seconds() for w in wait if w["s"] >= w["q"]]
        prov = self._q("SELECT provider, COUNT(*) AS calls, SUM(ok=0) AS errors, AVG(latency_ms) AS avg_ms FROM provider_calls GROUP BY provider")
        for p_ in prov:
            p_["error_rate"] = round((p_["errors"] or 0) / p_["calls"], 4) if p_["calls"] else None
            p_["avg_ms"] = round(p_["avg_ms"] or 0, 1)
        outcomes = {r["outcome"] or r["state"]: r["n"] for r in self._q("SELECT outcome, state, COUNT(*) AS n FROM jobs WHERE state IN ('COMPLETED','COMPLETED_WITH_WARNINGS','FAILED','DEAD_LETTER','EXPIRED','CANCELLED') GROUP BY outcome, state")}
        approvals = self._q("SELECT requested_at, decided_at FROM approvals WHERE decided_at IS NOT NULL")
        aw = [(parse_iso(a["decided_at"]) - parse_iso(a["requested_at"])).total_seconds() for a in approvals]
        sched_late = self._q("SELECT lateness_seconds FROM schedule_runs WHERE status IN ('fired','catchup_fired') ORDER BY fired_at DESC LIMIT 200")
        ver_pass = c.get("jobs_terminal_completed", 0)
        return {
            "generated_at": iso(now), "counters": c,
            "jobs": {"outcomes": outcomes, "recovered_total": c.get("lease_expiries", 0) + c.get("checkpoint_resumes", 0)},
            "stage_durations": stage,
            "queue_wait_seconds": {"samples": len(waits), "avg": round(sum(waits) / len(waits), 3) if waits else None, "max": round(max(waits), 3) if waits else None},
            "retries": {"scheduled": c.get("retries_scheduled", 0), "dead_lettered": c.get("dead_lettered", 0)},
            "duplicates_suppressed": c.get("duplicate_trigger_suppressed", 0),
            "scheduler_lateness_seconds": {"samples": len(sched_late), "max": max([x["lateness_seconds"] for x in sched_late], default=None)},
            "leases": {"expired": c.get("lease_expiries", 0), "fenced_worker_aborts": c.get("fenced_worker_aborts", 0)},
            "providers": prov,
            "approval_wait_seconds": {"samples": len(aw), "avg": round(sum(aw) / len(aw), 1) if aw else None},
            "verification": {"repairs_verified": outcomes.get("repair_verified", 0), "repairs_blocked": outcomes.get("repair_blocked", 0)},
            "token_usage": {"status": "not_applicable", "detail": "no model calls are made"},
            "audit_chain": st.verify_chain(),
        }
