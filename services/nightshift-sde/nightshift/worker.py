"""Job pipeline and worker.

One attempt = claim (QUEUED → VALIDATING) → resume-point decision from the latest *valid* checkpoint → stage handlers.
Every handler: does its work, persists a checkpoint, then returns a ``Step`` describing the next (validated, fenced)
transition. Nothing in memory is the source of truth: a worker that dies at any point leaves a job the watchdog can
reclaim and the next attempt resumes from the last good checkpoint.

Safety properties enforced here (and covered by tests):
* investigation never executes repository code; only EXECUTING/TESTING touch a throwaway workspace copy;
* READY_TO_EXECUTE is the single gate to write-capable work and re-validates base tree, policy version, evidence
  freshness, write authorisation and approval scope/expiry/revocation EVERY time (including after resume);
* approval is re-validated again immediately before EXECUTING and TESTING (revocation mid-flight stops the repair);
* regression failure or verifier disagreement can never yield a successful repair outcome;
* a stale worker (lost lease / wrong fence) cannot write: every write is fenced.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path

from . import WORKFLOW_VERSION
from . import statemachine as sm
from .errors import (ApprovalExpired, ApprovalRejected, CancelRequested, Conflict, DeadlineExceeded, GateBlocked, LeaseLost,
                     PauseRequested, PermanentError, ReplanRequired, SimulatedCrash, TransientError)
from .evidence import build_findings, finding_id
from .manifests import inspect_repository
from .repair import ALLOWED_ACTIONS, apply_proposal, build_proposal
from .repo import copy_tree, git_head, resolve_repo_path, tree_hash
from .retry import classify_exception
from .risk import assess
from .store import Store
from .util import iso, jdumps, jloads, new_id, parse_iso, sha256_hex
from .verifier import verify

log = logging.getLogger("nightshift.worker")

MAX_DEPS_CHECKPOINTED = 5000


@dataclass
class Step:
    state: str
    reason: str
    detail: dict = field(default_factory=dict)
    updates: dict = field(default_factory=dict)


@dataclass
class Ctx:
    job: dict
    fence: int
    worker_id: str
    stages: dict
    stage_started: float = 0.0
    last_hb: float = 0.0
    crashed: bool = False
    lost: threading.Event = field(default_factory=threading.Event)
    heartbeat_stop: threading.Event = field(default_factory=threading.Event)


class Worker:
    def __init__(self, store: Store, settings, runner, governance, sandbox, notifier=None, *, worker_id: str | None = None,
                 fault=None, heartbeat_thread: bool = True):
        self.store, self.settings = store, settings
        self.runner, self.gov, self.sandbox, self.notifier = runner, governance, sandbox, notifier
        self.worker_id = worker_id or f"wrk_{os.getpid()}_{new_id('w')[-6:]}"
        self.fault = fault or (lambda point, ctx: None)  # tests inject SimulatedCrash here
        self.use_heartbeat_thread = heartbeat_thread
        self._handlers = {
            sm.VALIDATING: self._validating, sm.SNAPSHOTTING: self._snapshotting, sm.INSPECTING: self._inspecting,
            sm.RESEARCHING: self._researching, sm.EVIDENCE_REVIEW: self._evidence_review, sm.RISK_ASSESSMENT: self._risk,
            sm.READY_TO_EXECUTE: self._gate, sm.EXECUTING: self._executing, sm.TESTING: self._testing,
            sm.INDEPENDENT_VERIFICATION: self._verification,
        }

    # ------------------------------------------------------------------------------------ loop
    def run_once(self) -> dict | None:
        """Claim and run one job. Returns the job's final row for this attempt, or None if nothing was runnable."""
        self.store.upsert_worker(self.worker_id, "idle", None, version=WORKFLOW_VERSION)
        job = self.store.claim_next(self.worker_id, self.settings.lease_seconds)
        if not job:
            return None
        self.store.upsert_worker(self.worker_id, "busy", job["id"], version=WORKFLOW_VERSION)
        try:
            return self._run_job(job)
        finally:
            self.store.upsert_worker(self.worker_id, "idle", None, version=WORKFLOW_VERSION)

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                if self.run_once() is None:
                    stop.wait(self.settings.worker_poll_seconds)
            except Exception:  # noqa: BLE001 — the loop must survive; the job's lease/watchdog covers the rest
                log.exception("worker loop error")
                stop.wait(self.settings.worker_poll_seconds)

    # ------------------------------------------------------------------------------------ job runner
    def _run_job(self, job: dict) -> dict:
        import time
        ctx = Ctx(job=job, fence=job["fence"], worker_id=self.worker_id, stages={})
        hb = None
        if self.use_heartbeat_thread:
            hb = threading.Thread(target=self._heartbeat_loop, args=(ctx,), daemon=True)
            hb.start()
        try:
            while True:
                job = self.store.get_job(ctx.job["id"])
                ctx.job = job
                self._signals(ctx)
                if job["state"] not in sm.ACTIVE:
                    return job
                handler = self._handlers[job["state"]]
                ctx.stage_started = time.monotonic()
                self.fault("before:" + job["state"], ctx)
                try:
                    step = handler(ctx)
                except ReplanRequired as e:
                    new = self._replan(ctx, e)
                    if new["state"] in sm.ACTIVE:
                        continue
                    return new
                if step is None:
                    return self.store.get_job(job["id"])
                self.fault("after_work:" + job["state"], ctx)
                new = self._advance(ctx, step)
                self.fault("after:" + job["state"], ctx)
                if new["state"] not in sm.ACTIVE:
                    return new
        except LeaseLost:
            log.warning("job %s: lease lost; abandoning attempt (fenced out)", ctx.job["id"])
            self.store.incr("fenced_worker_aborts")
            return self.store.get_job(ctx.job["id"])
        except CancelRequested:
            return self._finish_cancel(ctx)
        except PauseRequested:
            return self._finish_pause(ctx)
        except SimulatedCrash:
            ctx.crashed = True  # a real crash would skip cleanup; the watchdog reaps orphaned workspaces
            raise
        except DeadlineExceeded:
            return self._guard(lambda: self.store.transition(
                ctx.job["id"], sm.EXPIRED, actor=self.worker_id, source="worker", reason_code="JOB_DEADLINE_EXCEEDED", fence=ctx.fence,
                worker_id=self.worker_id, updates={"outcome": "expired", "error": self.store._err(
                    "JOB_DEADLINE_EXCEEDED", "job exceeded its maximum duration", "permanent")}), ctx)
        except ApprovalRejected as e:
            return self._approval_stop(ctx, e)
        except ApprovalExpired:
            return self._guard(lambda: self.store.transition(
                ctx.job["id"], sm.EXPIRED, actor=self.worker_id, source="worker", reason_code="APPROVAL_EXPIRED", fence=ctx.fence,
                worker_id=self.worker_id, updates={"outcome": "approval_expired", "error": self.store._err(
                    "APPROVAL_EXPIRED", "the approval expired before the repair could run", "permanent", category="gate_blocked")}), ctx)
        except GateBlocked as e:
            self.store.incr("gate_blocked")
            return self._guard(lambda: self.store.fail_permanent(
                ctx.job["id"], fence=ctx.fence, worker_id=self.worker_id, code=e.code, message=e.message, category="gate_blocked",
                outcome="repair_blocked", extra=e.extra), ctx)
        except PermanentError as e:
            return self._guard(lambda: self.store.fail_permanent(
                ctx.job["id"], fence=ctx.fence, worker_id=self.worker_id, code=e.code, message=e.message, extra=e.extra), ctx)
        except Exception as e:  # noqa: BLE001 — classified; SimulatedCrash is a BaseException and is NOT caught
            kind, code, retry_after = classify_exception(e)
            log.warning("job %s: %s error %s: %s", ctx.job["id"], kind, code, e)
            if kind == "transient":
                return self._guard(lambda: self.store.fail_transient(
                    ctx.job["id"], fence=ctx.fence, worker_id=self.worker_id, code=code, message=str(e), retry_after=retry_after), ctx)
            return self._guard(lambda: self.store.fail_permanent(
                ctx.job["id"], fence=ctx.fence, worker_id=self.worker_id, code=code, message=str(e)), ctx)
        finally:
            ctx.heartbeat_stop.set()
            if not ctx.crashed:
                self._cleanup_workspace(ctx.job["id"])

    def _guard(self, fn, ctx: Ctx) -> dict:
        try:
            return fn()
        except LeaseLost:
            self.store.incr("fenced_worker_aborts")
            return self.store.get_job(ctx.job["id"])
        except Conflict:
            # an operator cancel can land between the failure and its recording: cancellation wins
            if self.store.get_job(ctx.job["id"])["state"] == sm.CANCEL_REQUESTED:
                return self._finish_cancel(ctx)
            raise

    def _heartbeat_loop(self, ctx: Ctx) -> None:
        interval = max(0.2, self.settings.lease_seconds / 3.0)
        while not ctx.heartbeat_stop.wait(interval):
            try:
                self.store.heartbeat(ctx.job["id"], ctx.worker_id, ctx.fence, self.settings.lease_seconds)
                self.store.upsert_worker(ctx.worker_id, "busy", ctx.job["id"], version=WORKFLOW_VERSION)
            except LeaseLost:
                ctx.lost.set()
                return
            except Exception:  # noqa: BLE001
                log.exception("heartbeat failed")

    # ------------------------------------------------------------------------------------ signals / transitions
    def _signals(self, ctx: Ctx, note: str | None = None) -> None:
        """Cooperative checks: lease, cancel, pause, deadline, stage timeout. Also renews the lease."""
        import time
        if ctx.lost.is_set():
            raise LeaseLost("heartbeat thread detected lease loss")
        job = self.store.get_job(ctx.job["id"])
        if job["fence"] != ctx.fence or job["lease_owner"] != ctx.worker_id:
            raise LeaseLost(f"fence changed ({ctx.fence} → {job['fence']})")
        if job["state"] == sm.CANCEL_REQUESTED or job["cancel_requested"]:
            raise CancelRequested()
        if job["deadline_at"] and iso(self.store.clock.now()) >= job["deadline_at"]:
            raise DeadlineExceeded()
        if job["pause_requested"] and job["state"] in sm.ACTIVE:
            raise PauseRequested()
        if ctx.stage_started and time.monotonic() - ctx.stage_started > job["stage_timeout_seconds"]:
            raise TransientError("STAGE_TIMEOUT", f"stage {job['state']} exceeded {job['stage_timeout_seconds']}s")
        if note or time.monotonic() - ctx.last_hb > max(0.5, self.settings.lease_seconds / 4.0):
            ctx.last_hb = time.monotonic()
            self.store.heartbeat(job["id"], ctx.worker_id, ctx.fence, self.settings.lease_seconds, note=note)

    def _advance(self, ctx: Ctx, step: Step) -> dict:
        try:
            return self.store.transition(
                ctx.job["id"], step.state, actor=self.worker_id, source="worker", reason_code=step.reason, detail=step.detail,
                fence=ctx.fence, worker_id=self.worker_id, updates=step.updates, expect_from=sm.ACTIVE)
        except Conflict:
            if self.store.get_job(ctx.job["id"])["state"] == sm.CANCEL_REQUESTED:
                raise CancelRequested()
            raise

    def _checkpoint(self, ctx: Ctx, stage: str, data: dict, *, base_tree=None, evidence_retrieved_at=None, policy=None) -> None:
        cps = ctx.stages
        base = base_tree or (cps.get("snapshot", {}).get("base_tree") if cps.get("snapshot") else None)
        base_commit = cps.get("snapshot", {}).get("data", {}).get("commit") if cps.get("snapshot") else None
        pol = policy or cps.get("risk", {}).get("data", {}).get("policy") or {}
        self.store.save_checkpoint(ctx.job["id"], fence=ctx.fence, worker_id=ctx.worker_id, stage=stage, data=data,
                                   base_tree=base, base_commit=base_commit, policy_name=pol.get("name"),
                                   policy_version=pol.get("version"), evidence_retrieved_at=evidence_retrieved_at)
        row = self.store.valid_checkpoints(ctx.job["id"]).get(stage)
        if row:
            ctx.stages[stage] = row
        self.fault("checkpoint:" + stage, ctx)

    # ------------------------------------------------------------------------------------ terminal handlers
    def _finish_cancel(self, ctx: Ctx) -> dict:
        def go():
            self.store.db.read()
            with self.store.db.tx() as c:
                c.execute("UPDATE approvals SET status='superseded' WHERE job_id=? AND status IN ('pending','approved')", (ctx.job["id"],))
            return self.store.transition(ctx.job["id"], sm.CANCELLED, actor=self.worker_id, source="worker", reason_code="CANCELLED_BY_WORKER",
                                         fence=ctx.fence, worker_id=self.worker_id, updates={"outcome": "cancelled", "fence": ctx.fence + 1})
        return self._guard(go, ctx)

    def _finish_pause(self, ctx: Ctx) -> dict:
        return self._guard(lambda: self.store.transition(
            ctx.job["id"], sm.PAUSED, actor=self.worker_id, source="worker", reason_code="PAUSED_BY_OPERATOR", fence=ctx.fence,
            worker_id=self.worker_id, updates={"pause_requested": 0}), ctx)

    def _replan(self, ctx: Ctx, e: ReplanRequired) -> dict:
        """Invalidate checkpoints after ``e.after_stage``, supersede approvals (fresh approval will be required) and re-enter
        the pipeline. If the current state has no direct edge to the target, the job is re-queued and a new attempt re-plans."""
        job = self.store.get_job(ctx.job["id"])
        if job["replan_count"] + 1 > self.settings.max_replans:
            return self._guard(lambda: self.store.fail_permanent(
                job["id"], fence=ctx.fence, worker_id=self.worker_id, code="REPLAN_LIMIT_EXCEEDED",
                message=f"replanned {job['replan_count']} times; last reason: {e.reason}"), ctx)

        def go():
            self.store.invalidate_checkpoints(job["id"], after_stage=e.after_stage, reason=e.reason)
            with self.store.db.tx() as c:
                c.execute("UPDATE approvals SET status='superseded' WHERE job_id=? AND status IN ('pending','approved')", (job["id"],))
            self.store.incr("replans")
            target = e.target_state if sm.can_transition(job["state"], e.target_state) else sm.QUEUED
            return self.store.transition(job["id"], target, actor=self.worker_id, source="worker", reason_code="REPLAN_" + e.reason,
                                         fence=ctx.fence, worker_id=self.worker_id,
                                         detail={"after_stage": e.after_stage, "reason": e.reason, "fresh_approval_required": True,
                                                 "requested_target": e.target_state},
                                         updates={"replan_count": job["replan_count"] + 1})
        new = self._guard(go, ctx)
        self._load_stages(ctx)
        return new

    def _approval_stop(self, ctx: Ctx, e: ApprovalRejected) -> dict:
        state = self.store.get_job(ctx.job["id"])["state"]
        if state == sm.READY_TO_EXECUTE:
            return self._guard(lambda: self.store.transition(
                ctx.job["id"], sm.COMPLETED_WITH_WARNINGS, actor=self.worker_id, source="worker", reason_code="APPROVAL_" + e.outcome.upper(),
                fence=ctx.fence, worker_id=self.worker_id, detail={"reason": e.reason},
                updates={"outcome": e.outcome, "result": {"repair_applied": False, "note": e.reason}}), ctx)
        return self._guard(lambda: self.store.fail_permanent(
            ctx.job["id"], fence=ctx.fence, worker_id=self.worker_id, code="APPROVAL_REVOKED" if "revoked" in e.outcome else "APPROVAL_INVALID",
            message=e.reason, category="gate_blocked", outcome=e.outcome), ctx)

    # ------------------------------------------------------------------------------------ helpers
    def _repo(self, ctx: Ctx) -> tuple[dict, Path]:
        repo = self.store.get_repo(ctx.job["repo_id"])
        if repo["archived_at"]:
            raise PermanentError("REPO_UNAVAILABLE", "repository is archived")
        return repo, resolve_repo_path(self.settings.repo_root, repo["rel_path"])

    def _load_stages(self, ctx: Ctx) -> None:
        ctx.stages = self.store.valid_checkpoints(ctx.job["id"])

    def _stage_data(self, ctx: Ctx, stage: str) -> dict:
        cp = ctx.stages.get(stage)
        if cp is None:
            raise ReplanRequired(None, sm.SNAPSHOTTING, f"MISSING_CHECKPOINT_{stage.upper()}")
        return cp["data"]

    def _base_tree(self, ctx: Ctx) -> str:
        return self._stage_data(ctx, "snapshot")["tree_hash"]

    def _assert_repo_unchanged(self, ctx: Ctx, root: Path) -> None:
        if tree_hash(root)["tree_hash"] != self._base_tree(ctx):
            raise ReplanRequired(None, sm.SNAPSHOTTING, "BASE_CHANGED")

    def _workspace(self, job_id: str) -> Path:
        return Path(self.settings.workspaces_dir) / job_id

    def _cleanup_workspace(self, job_id: str) -> None:
        ws = self._workspace(job_id)
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)

    def _preconditions(self, ctx: Ctx, root: Path, *, write: bool) -> None:
        """Resume/gate preconditions. Raises ReplanRequired (never silently continues on stale state)."""
        stages = ctx.stages
        if not stages:
            return
        snap = stages.get("snapshot")
        first_cp = next(iter(stages.values()))
        if first_cp["workflow_version"] != WORKFLOW_VERSION:
            raise ReplanRequired(None, sm.SNAPSHOTTING, "WORKFLOW_VERSION_INCOMPATIBLE")
        if snap and tree_hash(root)["tree_hash"] != snap["data"]["tree_hash"]:
            raise ReplanRequired(None, sm.SNAPSHOTTING, "BASE_CHANGED")
        if snap and git_head(root) != snap["data"].get("commit"):
            raise ReplanRequired(None, sm.SNAPSHOTTING, "BASE_COMMIT_CHANGED")
        risk = stages.get("risk")
        if risk:
            pol = risk["data"]["policy"]
            latest = self.store.get_policy(pol["name"])
            if latest["version"] != pol["version"]:
                raise ReplanRequired("evidence_review", sm.RISK_ASSESSMENT, "POLICY_CHANGED")
        research = stages.get("research")
        if research and (write or stages.get("risk")):
            oldest = research["data"].get("retrieved_at_min")
            if oldest and oldest < iso(self.store.clock.now() - timedelta(seconds=self.settings.evidence_max_age_seconds)):
                raise ReplanRequired("inspect", sm.RESEARCHING, "EVIDENCE_STALE")

    def _scope(self, ctx: Ctx, proposal: dict, policy: dict) -> dict:
        snap = self._stage_data(ctx, "snapshot")
        return {"repo_id": ctx.job["repo_id"], "base_tree": snap["tree_hash"], "base_commit": snap.get("commit"),
                "paths": sorted(proposal["allowed_paths"]), "actions": list(ALLOWED_ACTIONS), "diff_hash": proposal["diff_hash"],
                "policy": {"name": policy["name"], "version": policy["version"]}, "finding_id": proposal["finding_id"],
                "change": f"{proposal['package']} {proposal['from_version']} → {proposal['to_version']}"}

    def _current_approval(self, job_id: str, scope_hash: str):
        r = self.store.db.read().execute(
            "SELECT * FROM approvals WHERE job_id=? AND status!='superseded' ORDER BY requested_at DESC, rowid DESC", (job_id,)).fetchall()
        for a in r:
            if a["scope_hash"] == scope_hash:
                return dict(a)
        return None

    # ------------------------------------------------------------------------------------ stages
    def _validating(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        self._load_stages(ctx)
        if not ctx.stages:
            return Step(sm.SNAPSHOTTING, "FRESH_START")
        self._preconditions(ctx, root, write=False)
        last = list(ctx.stages)[-1]
        target = sm.RESUME_STATE[last]
        self.store.incr("checkpoint_resumes")
        return Step(target, "RESUMED_FROM_CHECKPOINT", {"checkpoint_stage": last, "seq": ctx.stages[last]["seq"],
                                                       "verified": ["workflow_version", "base_tree", "base_commit", "policy_version", "evidence_freshness"]})

    def _snapshotting(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        th = tree_hash(root)
        commit = git_head(root)
        sid = new_id("snp")
        with self.store.db.tx() as c:
            c.execute("INSERT INTO repo_snapshots(id, repo_id, job_id, tree_hash, commit_sha, file_count, taken_at) VALUES (?,?,?,?,?,?,?)",
                      (sid, repo["id"], ctx.job["id"], th["tree_hash"], commit, th["file_count"], iso(self.store.clock.now())))
        self._checkpoint(ctx, "snapshot", {"tree_hash": th["tree_hash"], "file_count": th["file_count"], "commit": commit,
                                           "symlinks_skipped": th["symlinks_skipped"], "snapshot_id": sid}, base_tree=th["tree_hash"])
        return Step(sm.INSPECTING, "SNAPSHOT_TAKEN", {"tree_hash": th["tree_hash"][:16], "files": th["file_count"]},
                    {"base_tree": th["tree_hash"], "base_commit": commit})

    def _inspecting(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        self._signals(ctx, "inspecting manifests (read-only; no repository code is executed)")
        res = inspect_repository(root)
        self._assert_repo_unchanged(ctx, root)
        deps = res["dependencies"][:MAX_DEPS_CHECKPOINTED]
        truncated = len(res["dependencies"]) > MAX_DEPS_CHECKPOINTED
        data = {"manifests": res["manifests"], "dependencies": deps, "issues": res["issues"], "injection_flags": res["injection_flags"],
                "symlinks_skipped": res["symlinks_skipped"], "truncated": truncated}
        self._checkpoint(ctx, "inspect", data)
        return Step(sm.RESEARCHING, "INSPECTION_DONE", {"manifests": len(res["manifests"]), "dependencies": len(deps)})

    def _researching(self, ctx: Ctx) -> Step:
        insp = self._stage_data(ctx, "inspect")
        pkgs = sorted({(d["ecosystem"], d["name"]) for d in insp["dependencies"] if d.get("version")})
        lookups, limitations, oldest = {}, [], None
        for eco, name in pkgs:
            self._signals(ctx, f"researching advisories: {name}")
            results, lim = self.runner.lookup_all(eco, name, corr=ctx.job["correlation_id"])
            limitations += lim
            lookups[f"{eco}|{name}"] = [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in results]
            for r in results:
                oldest = r.retrieved_at if oldest is None or r.retrieved_at < oldest else oldest
        data = {"lookups": lookups, "provider_limitations": limitations, "retrieved_at_min": oldest, "packages_checked": len(pkgs)}
        self._checkpoint(ctx, "research", data, evidence_retrieved_at=oldest)
        return Step(sm.EVIDENCE_REVIEW, "RESEARCH_DONE", {"packages_checked": len(pkgs)})

    def _evidence_review(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        insp, research = self._stage_data(ctx, "inspect"), self._stage_data(ctx, "research")
        lookups = {tuple(k.split("|", 1)): v for k, v in research["lookups"].items()}
        built = build_findings(repo_id=repo["id"], dependencies=insp["dependencies"], lookups=lookups, now=self.store.clock.now(),
                               max_age_seconds=self.settings.evidence_max_age_seconds)
        now = iso(self.store.clock.now())
        job_id = ctx.job["id"]
        with self.store.db.tx() as c:
            seen = set()
            for f in built["findings"]:
                seen.add(f["id"])
                c.execute(
                    "INSERT INTO findings(id, repo_id, last_job_id, package, ecosystem, installed_version, relationship, manifest_paths,"
                    " advisory_ids, affected_ranges, fixed_candidates, selected_fix, severity, reason_codes, evidence_status, confidence,"
                    " limitations, recommended_action, requires_approval, status, first_seen_at, last_seen_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(id) DO UPDATE SET last_job_id=excluded.last_job_id, installed_version=excluded.installed_version,"
                    " relationship=excluded.relationship, manifest_paths=excluded.manifest_paths, affected_ranges=excluded.affected_ranges,"
                    " fixed_candidates=excluded.fixed_candidates, selected_fix=excluded.selected_fix, severity=excluded.severity,"
                    " reason_codes=excluded.reason_codes, evidence_status=excluded.evidence_status, confidence=excluded.confidence,"
                    " limitations=excluded.limitations, status='open', last_seen_at=excluded.last_seen_at",
                    (f["id"], repo["id"], job_id, f["package"], f["ecosystem"], f["installed_version"], f["relationship"],
                     jdumps(f["manifest_paths"]), jdumps(f["advisory_ids"]), jdumps(f["affected_ranges"]), jdumps(f["fixed_candidates"]),
                     f["selected_fix"], f["severity"], jdumps(f["reason_codes"]), f["evidence_status"], f["confidence"],
                     jdumps(f["limitations"]), "pending risk assessment", 1, "open", now, now))
                c.execute("INSERT OR IGNORE INTO finding_observations(finding_id, job_id, repo_id, observed_at, installed_version, severity,"
                          " evidence_status) VALUES (?,?,?,?,?,?,?)",
                          (f["id"], job_id, repo["id"], now, f["installed_version"], f["severity"], f["evidence_status"]))
                for ev in f["evidence"]:
                    eid = "evd_" + sha256_hex(f"{job_id}|{f['id']}|{ev['provider']}|{ev['advisory_id']}")[:16]
                    c.execute(
                        "INSERT OR IGNORE INTO evidence(id, job_id, finding_id, repo_id, source, source_mode, advisory_id, package, ecosystem,"
                        " url, retrieved_at, content_hash, summary, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (eid, job_id, f["id"], repo["id"], ev["provider"], ev["mode"], ev["advisory_id"], f["package"], f["ecosystem"],
                         ev.get("url"), ev["retrieved_at"], sha256_hex(jdumps(ev)), jdumps({"summary": ev["summary"]}), "[]"))
            # findings this inspection no longer detects are marked resolved (an observation, not a repair claim)
            for r in c.execute("SELECT id FROM findings WHERE repo_id=? AND status='open'", (repo["id"],)).fetchall():
                if r["id"] not in seen:
                    c.execute("UPDATE findings SET status='no_longer_detected', last_seen_at=? WHERE id=?", (now, r["id"]))
        data = {"findings": built["findings"], "unresolved": built["unresolved"], "limitations": built["limitations"]}
        self._checkpoint(ctx, "evidence_review", data, evidence_retrieved_at=research.get("retrieved_at_min"))
        return Step(sm.RISK_ASSESSMENT, "EVIDENCE_RECONCILED", {"findings": len(built["findings"]), "unresolved": len(built["unresolved"])})

    def _risk(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        ev = self._stage_data(ctx, "evidence_review")
        findings = ev["findings"]
        allow = bool(ctx.job["allow_repair"] and repo["allow_repair"])
        if "risk" in ctx.stages:
            assessment = ctx.stages["risk"]["data"]
            policy = self.store.get_policy(assessment["policy"]["name"], assessment["policy"]["version"])
        else:
            policy = self.store.get_policy(ctx.job["policy_name"])
            assessment = assess(findings, allow_repair=allow, policy=policy, test_command_key=repo["test_command_key"])
            with self.store.db.tx() as c:
                c.execute("INSERT INTO risk_assessments(id, job_id, policy_name, policy_version, score, tier, reason_codes, repair_decision, detail, created_at)"
                          " VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (new_id("rsk"), ctx.job["id"], policy["name"], policy["version"], assessment["score"], assessment["tier"],
                           jdumps(assessment["reason_codes"]), assessment["repair_decision"], jdumps(assessment), iso(self.store.clock.now())))
                for p in assessment["per_finding"]:
                    cand = assessment["candidate"] and assessment["candidate"]["finding_id"] == p["finding_id"]
                    f = next(x for x in findings if x["id"] == p["finding_id"])
                    if cand:
                        action = (f"Bump {f['package']} {f['installed_version']} → {f['selected_fix']} "
                                  + ("(requires approval before any change)" if assessment["approval_required"] else "(policy permits proceeding without approval)"))
                    elif f["selected_fix"] and p["repair_blockers"]:
                        action = "Manual: upgrade to " + f["selected_fix"] + "; automated repair blocked by " + ", ".join(p["repair_blockers"])
                    else:
                        action = "Manual review required: " + ", ".join(p["repair_blockers"] or f["reason_codes"])
                    c.execute("UPDATE findings SET risk_score=?, risk_tier=?, reason_codes=?, recommended_action=?, requires_approval=? WHERE id=?",
                              (p["score"], p["tier"], jdumps(sorted(set(f["reason_codes"]) | set(p["reason_codes"]))), action,
                               1 if (cand and assessment["approval_required"]) or not cand else 0, p["finding_id"]))
            self._checkpoint(ctx, "risk", assessment, policy={"name": policy["name"], "version": policy["version"]},
                             evidence_retrieved_at=ctx.stages.get("research", {}).get("data", {}).get("retrieved_at_min"))
        upd = {"policy_version": policy["version"]}
        cand = assessment["candidate"]
        if cand is None:
            insp = ctx.stages.get("inspect", {}).get("data", {})
            issues = [i for i in insp.get("issues", []) if i.get("severity") == "warning"]
            limited = bool(findings or ev["unresolved"] or ev["limitations"] or issues)
            coverage = {"manifests": len(insp.get("manifests", [])), "dependencies_parsed": len(insp.get("dependencies", [])),
                        "inspection_warnings": len(issues), "unresolved_dependencies": len(ev["unresolved"])}
            note = "Investigation complete. No repair was performed or verified."
            if issues or ev["unresolved"]:
                note += (" Coverage was INCOMPLETE (" + f"{len(issues)} manifest warning(s), {len(ev['unresolved'])} dependency/dependencies without a "
                         "pinned version), so 'no findings' only covers the dependencies that could be parsed and matched.")
            result = {"findings": len(findings), "repair_applied": False, "repair_decision": assessment["repair_decision"],
                      "blockers": assessment["blockers"], "tier": assessment["tier"], "coverage": coverage, "note": note}
            upd.update(outcome="investigation_only" if findings else "no_findings", result=result)
            return Step(sm.COMPLETED_WITH_WARNINGS if limited else sm.COMPLETED, "INVESTIGATION_COMPLETE", {"decision": assessment["repair_decision"]}, upd)
        # a repair candidate exists → build the proposal from the exact base tree
        if "proposal" not in ctx.stages:
            self._assert_repo_unchanged(ctx, root)
            finding = next(f for f in findings if f["id"] == cand["finding_id"])
            proposal = build_proposal(root, finding)
            self.store.add_artifact(ctx.job["id"], "patch", "proposal.diff", proposal["diff"])
            self._checkpoint(ctx, "proposal", {"proposal": proposal, "approval_required": assessment["approval_required"]})
        return Step(sm.READY_TO_EXECUTE, "REPAIR_PROPOSED", {"package": cand["package"], "approval_required": assessment["approval_required"]}, upd)

    def _request_approval(self, ctx: Ctx, scope: dict) -> dict:
        existing = self._current_approval(ctx.job["id"], self.gov_scope_hash(scope))
        if existing and existing["status"] in ("pending", "approved"):
            return existing
        expires = iso(self.store.clock.now() + timedelta(seconds=self.settings.approval_ttl_seconds))
        a = self.gov.request_approval(job=ctx.job, scope=scope, requested_by=ctx.job["requested_by"], expires_at=expires)
        if self.notifier:
            self.notifier.enqueue(ctx.job["id"], "approval_requested", {"job_id": ctx.job["id"], "approval_id": a["id"], "repo_id": ctx.job["repo_id"],
                                                                         "expires_at": expires, "note": "Open the NightShift console to review; this message is not an approval."})
        return a

    @staticmethod
    def gov_scope_hash(scope: dict) -> str:
        from .governance import scope_hash
        return scope_hash(scope)

    def _gate(self, ctx: Ctx) -> Step | None:
        """The only door to write-capable work. Fail closed."""
        repo, root = self._repo(ctx)
        self._load_stages(ctx)
        self._preconditions(ctx, root, write=True)
        if "proposal" not in ctx.stages or "risk" not in ctx.stages:
            raise ReplanRequired("evidence_review", sm.RISK_ASSESSMENT, "MISSING_PROPOSAL")
        prop_cp = ctx.stages["proposal"]["data"]
        proposal, required = prop_cp["proposal"], prop_cp["approval_required"]
        pol = ctx.stages["risk"]["data"]["policy"]
        policy = self.store.get_policy(pol["name"], pol["version"])
        if not (ctx.job["allow_repair"] and repo["allow_repair"]):
            raise ApprovalRejected("repair_not_authorized", "write-capable repair is not authorised for this job/repository")
        scope = self._scope(ctx, proposal, policy)
        approval_id = None
        if required:
            appr = self._current_approval(ctx.job["id"], self.gov_scope_hash(scope))
            if appr is None:
                a = self._request_approval(ctx, scope)
                return Step(sm.WAITING_FOR_APPROVAL, "APPROVAL_REQUESTED", {"approval_id": a["id"], "expires_at": a["expires_at"],
                                                                           "scope_hash": a["scope_hash"], "provider": self.gov.mode})
            v = self.gov.validate_for_execution(appr["id"], scope)
            if v["code"] == "NOT_APPROVED":
                return Step(sm.WAITING_FOR_APPROVAL, "APPROVAL_PENDING", {"approval_id": appr["id"], "expires_at": appr["expires_at"]})
            if v["code"] == "EXPIRED":
                raise ApprovalExpired()
            if v["code"] in ("REVOKED", "REJECTED"):
                raise ApprovalRejected("repair_revoked" if v["code"] == "REVOKED" else "repair_rejected", f"approval {v['code'].lower()}: {v.get('detail') or ''}")
            if not v["valid"]:
                raise ReplanRequired("evidence_review", sm.RISK_ASSESSMENT, "APPROVAL_" + v["code"])
            approval_id = appr["id"]
        self._checkpoint(ctx, "ready", {"approval_id": approval_id, "scope_hash": self.gov_scope_hash(scope), "approval_required": required,
                                        "validated_at": iso(self.store.clock.now())})
        return Step(sm.EXECUTING, "GATE_PASSED", {"approval_id": approval_id})

    def _revalidate_approval(self, ctx: Ctx) -> None:
        ready = ctx.stages.get("ready", {}).get("data") or {}
        if not ready.get("approval_required"):
            return
        prop = ctx.stages["proposal"]["data"]["proposal"]
        pol = ctx.stages["risk"]["data"]["policy"]
        scope = self._scope(ctx, prop, self.store.get_policy(pol["name"], pol["version"]))
        v = self.gov.validate_for_execution(ready["approval_id"], scope)
        if not v["valid"]:
            if v["code"] == "EXPIRED":
                raise ApprovalExpired()
            raise ApprovalRejected("repair_revoked" if v["code"] in ("REVOKED", "SUPERSEDED") else "repair_blocked", f"approval no longer valid: {v['code']}")

    def _executing(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        self._load_stages(ctx)
        self._revalidate_approval(ctx)
        probe = self.sandbox.preflight()
        if not probe["available"]:
            raise GateBlocked("SANDBOX_UNSAFE", probe["reason"] or "no safe sandbox", extra={"sandbox": probe})
        if repo["test_command_key"] == "none":
            raise GateBlocked("NO_REGRESSION_GATE", "repository has no regression command configured")
        self._assert_repo_unchanged(ctx, root)  # TOCTOU: re-check the base immediately before writing
        proposal = ctx.stages["proposal"]["data"]["proposal"]
        ws = self._workspace(ctx.job["id"])
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)  # idempotent re-execution after resume
        base_ws, patched_ws = ws / "base", ws / "patched"
        copy_tree(root, base_ws)
        copy_tree(root, patched_ws)
        if tree_hash(base_ws)["tree_hash"] != self._base_tree(ctx):
            raise ReplanRequired(None, sm.SNAPSHOTTING, "BASE_CHANGED_DURING_COPY")
        self._signals(ctx, "applying proposal to isolated workspace copy")
        apply_proposal(patched_ws, proposal)
        self._checkpoint(ctx, "execute", {"patched_tree_hash": tree_hash(patched_ws)["tree_hash"], "paths": proposal["allowed_paths"],
                                          "workspace": "isolated copy (the registered repository was not modified)"})
        return Step(sm.TESTING, "PROPOSAL_APPLIED_IN_WORKSPACE", {"paths": proposal["allowed_paths"]})

    def _testing(self, ctx: Ctx) -> Step:
        repo, _ = self._repo(ctx)
        self._load_stages(ctx)
        self._revalidate_approval(ctx)
        ws = self._workspace(ctx.job["id"])
        if not (ws / "patched").is_dir():
            raise ReplanRequired("proposal", sm.READY_TO_EXECUTE, "WORKSPACE_MISSING")
        cancel_cb = lambda: (self._signals(ctx, "running regression tests in sandbox"), False)[1]
        results = {}
        for label in ("baseline", "patched"):
            sub = ws / ("base" if label == "baseline" else "patched")
            r = self.sandbox.run(repo["test_command_key"], sub, timeout=self.settings.sandbox_timeout_seconds, cancel_cb=cancel_cb)
            self.store.add_artifact(ctx.job["id"], "test_log", f"{label}.log",
                                    f"exit={r.exit_code} timed_out={r.timed_out} duration={r.duration_seconds}s\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
            results[label] = {"exit_code": r.exit_code, "timed_out": r.timed_out, "duration_seconds": r.duration_seconds, "isolation": r.isolation}
            if label == "baseline" and (r.exit_code != 0 or r.timed_out):
                raise GateBlocked("BASELINE_TESTS_FAILING", "the unmodified repository fails its regression gate; the repair cannot be attributed",
                                  extra={"tests": results})
            if label == "patched" and (r.exit_code != 0 or r.timed_out):
                raise GateBlocked("REGRESSION_TESTS_FAILED", "the proposed change fails the regression gate", extra={"tests": results})
        self._checkpoint(ctx, "test", results)
        return Step(sm.INDEPENDENT_VERIFICATION, "TESTS_PASSED", {"baseline_exit": results["baseline"]["exit_code"], "patched_exit": results["patched"]["exit_code"]})

    def _verification(self, ctx: Ctx) -> Step:
        repo, root = self._repo(ctx)
        self._load_stages(ctx)
        self._revalidate_approval(ctx)
        self._assert_repo_unchanged(ctx, root)
        ws = self._workspace(ctx.job["id"])
        proposal = ctx.stages["proposal"]["data"]["proposal"]
        findings = ctx.stages["evidence_review"]["data"]["findings"]
        finding = next(f for f in findings if f["id"] == proposal["finding_id"])
        research = ctx.stages["research"]["data"]
        lookups = {tuple(k.split("|", 1)): v for k, v in research["lookups"].items()}
        verdict = verify(base=ws / "base", patched=ws / "patched", proposal=proposal, finding=finding, lookups=lookups,
                         now=self.store.clock.now(), max_age_seconds=self.settings.evidence_max_age_seconds, repo_id=repo["id"],
                         original_finding_ids=[f["id"] for f in findings], tests=ctx.stages["test"]["data"])
        self.store.add_artifact(ctx.job["id"], "verifier_report", "verifier.json", jdumps(verdict))
        if verdict["verdict"] != "agree":
            failed = [c["name"] for c in verdict["checks"] if not c["ok"]]
            raise GateBlocked("VERIFIER_DISAGREEMENT", "independent verification disagreed: " + ", ".join(failed), extra={"failed_checks": failed})
        ready = ctx.stages["ready"]["data"]
        appr = self.gov.get(ready["approval_id"]) if ready.get("approval_id") else None
        snap = ctx.stages["snapshot"]["data"]
        proof = {
            "kind": "nightshift.repair_proof", "schema": 1, "job_id": ctx.job["id"], "correlation_id": ctx.job["correlation_id"],
            "repository": {"id": repo["id"], "slug": repo["slug"]}, "base": {"tree_hash": snap["tree_hash"], "commit": snap.get("commit")},
            "change": {"package": proposal["package"], "from": proposal["from_version"], "to": proposal["to_version"],
                       "paths": proposal["allowed_paths"], "diff_sha256": proposal["diff_hash"]},
            "evidence": [{"advisory_id": e["advisory_id"], "provider": e["provider"], "mode": e["mode"], "retrieved_at": e["retrieved_at"]} for e in finding["evidence"]],
            "policy": ctx.stages["risk"]["data"]["policy"],
            "approval": None if not appr else {"id": appr["id"], "provider": appr["provider_label"], "approver": appr["decided_by"],
                                               "decided_at": appr["decided_at"], "scope_hash": appr["scope_hash"]},
            "tests": ctx.stages["test"]["data"], "verifier": {"label": verdict["verifier"], "verdict": verdict["verdict"], "checks": verdict["checks"]},
            "limits": ["No pull request was created.", "Nothing was merged or deployed.", "The registered repository was not modified; apply the patch artifact deliberately.",
                       "Isolation: process-level sandbox only (see SECURITY.md)."],
            "generated_at": iso(self.store.clock.now()),
        }
        body = jdumps(proof)
        proof["sha256_of_body_without_hash"] = sha256_hex(body)
        art = self.store.add_artifact(ctx.job["id"], "repair_proof", "repair-proof.json", jdumps(proof))
        self._checkpoint(ctx, "verify", {"verdict": verdict["verdict"], "proof_artifact": art["id"]})
        remaining = len(findings) - 1
        result = {"repair_applied": False, "repair_verified": True, "patch_artifact": "proposal.diff", "repair_proof_artifact": "repair-proof.json",
                  "remaining_findings": remaining, "note": "Verified patch artifact produced. It has NOT been applied to the repository, no PR was created, nothing was merged."}
        return Step(sm.COMPLETED_WITH_WARNINGS if remaining else sm.COMPLETED, "REPAIR_VERIFIED", {"remaining_findings": remaining},
                    {"outcome": "repair_verified", "result": result})
