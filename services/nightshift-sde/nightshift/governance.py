"""Governance adapter (UNWIND integration point) + a clearly-labelled DEV STUB.

The real UNWIND Governance Core contract was NOT available when this standalone feature was built, so
``DevStubGovernance`` is a narrow local implementation of the same logical contract:

    request_approval(scope) → decide(approve|reject) → validate_for_execution(current_scope) → revoke

* Approval is scoped to: repository, base tree/commit, permitted paths + actions, the proposal (diff) hash,
  policy version and an expiry. ANY change to that scope invalidates the grant (``SCOPE_MISMATCH``).
* Approval never covers merge or deployment (separate permissions; not implemented here).
* Notifications are not credentials: approvals happen only through the authenticated API.

The UI and every API response label this provider as "DEV STUB — not UNWIND".
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .errors import Conflict, Forbidden, NotFound
from .redact import REDACTOR
from .store import Store
from .util import canonical_json, iso, jloads, jdumps, new_id, sha256_hex


def scope_hash(scope: dict) -> str:
    return sha256_hex(canonical_json(scope))


class GovernanceProvider(ABC):
    name = "abstract"
    mode = "abstract"

    @abstractmethod
    def request_approval(self, *, job: dict, scope: dict, requested_by: str, expires_at: str) -> dict: ...

    @abstractmethod
    def decide(self, approval_id: str, *, approver: str, decision: str, note: str, enforce_sod: bool) -> dict: ...

    @abstractmethod
    def revoke(self, approval_id: str, *, actor: str, reason: str) -> dict: ...

    @abstractmethod
    def validate_for_execution(self, approval_id: str, current_scope: dict) -> dict: ...

    @abstractmethod
    def get(self, approval_id: str) -> dict: ...


class DevStubGovernance(GovernanceProvider):
    name = "dev-stub"
    mode = "DEV STUB — not UNWIND"

    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["scope"] = jloads(d["scope"], {})
        d["provider_label"] = DevStubGovernance.mode
        return d

    def get(self, approval_id: str) -> dict:
        r = self.store.db.read().execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not r:
            raise NotFound("approval not found", code="APPROVAL_NOT_FOUND")
        return self._row(r)

    def request_approval(self, *, job: dict, scope: dict, requested_by: str, expires_at: str) -> dict:
        with self.store.db.tx() as c:
            # any earlier open approval for this job is superseded: only ONE live scope per job
            c.execute("UPDATE approvals SET status='superseded' WHERE job_id=? AND status IN ('pending','approved')", (job["id"],))
            aid = new_id("apr")
            c.execute(
                "INSERT INTO approvals(id, job_id, repo_id, provider, status, scope, scope_hash, requested_by, requested_at, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (aid, job["id"], job["repo_id"], self.name, "pending", jdumps(scope), scope_hash(scope), requested_by,
                 iso(self.store.clock.now()), expires_at))
            self.store.emit("approval.requested", actor=requested_by, correlation_id=job["correlation_id"], job_id=job["id"],
                            repo_id=job["repo_id"], data={"approval_id": aid, "scope_hash": scope_hash(scope), "scope": scope,
                                                          "expires_at": expires_at, "provider": self.mode})
            return self.get(aid)

    def decide(self, approval_id: str, *, approver: str, decision: str, note: str = "", enforce_sod: bool = True) -> dict:
        if decision not in ("approve", "reject"):
            raise Conflict("decision must be approve or reject", code="VALIDATION_ERROR")
        with self.store.db.tx() as c:
            a = c.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not a:
                raise NotFound("approval not found", code="APPROVAL_NOT_FOUND")
            if a["status"] != "pending":
                raise Conflict(f"approval is {a['status']}, not pending", code="APPROVAL_NOT_PENDING")
            if a["expires_at"] <= iso(self.store.clock.now()):
                c.execute("UPDATE approvals SET status='expired' WHERE id=?", (approval_id,))
                self.store.emit("approval.expired", job_id=a["job_id"], repo_id=a["repo_id"], data={"approval_id": approval_id})
                raise Conflict("approval has expired", code="APPROVAL_EXPIRED")
            job = c.execute("SELECT requested_by FROM jobs WHERE id=?", (a["job_id"],)).fetchone()
            if enforce_sod and approver in (a["requested_by"], job["requested_by"] if job else None):
                raise Forbidden("separation of duties: the requester cannot approve their own request", code="SEPARATION_OF_DUTIES")
            status = "approved" if decision == "approve" else "rejected"
            c.execute("UPDATE approvals SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                      (status, approver, iso(self.store.clock.now()), REDACTOR.text(note)[:500], approval_id))
            self.store.emit("approval." + status, actor=approver, job_id=a["job_id"], repo_id=a["repo_id"],
                            data={"approval_id": approval_id, "scope_hash": a["scope_hash"], "note": note[:200]})
            return self.get(approval_id)

    def revoke(self, approval_id: str, *, actor: str, reason: str = "") -> dict:
        with self.store.db.tx() as c:
            a = c.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if not a:
                raise NotFound("approval not found", code="APPROVAL_NOT_FOUND")
            if a["status"] not in ("approved", "pending"):
                raise Conflict(f"approval is {a['status']}; only pending/approved grants can be revoked", code="APPROVAL_NOT_REVOCABLE")
            c.execute("UPDATE approvals SET status='revoked', revoked_by=?, revoked_at=?, revoke_reason=? WHERE id=?",
                      (actor, iso(self.store.clock.now()), REDACTOR.text(reason)[:500], approval_id))
            self.store.emit("approval.revoked", actor=actor, job_id=a["job_id"], repo_id=a["repo_id"],
                            data={"approval_id": approval_id, "reason": reason[:200]})
            return self.get(approval_id)

    def validate_for_execution(self, approval_id: str, current_scope: dict) -> dict:
        """Return {valid, code, detail}. Called at the gate, and again before each write-capable stage."""
        a = self.get(approval_id)
        now = iso(self.store.clock.now())
        if a["status"] == "revoked":
            return {"valid": False, "code": "REVOKED", "detail": a.get("revoke_reason")}
        if a["status"] == "rejected":
            return {"valid": False, "code": "REJECTED", "detail": a.get("decision_note")}
        if a["status"] == "superseded":
            return {"valid": False, "code": "SUPERSEDED", "detail": "a newer approval request replaced this one"}
        if a["status"] == "pending":
            return {"valid": False, "code": "NOT_APPROVED", "detail": "approval still pending"}
        if a["status"] == "expired" or a["expires_at"] <= now:
            return {"valid": False, "code": "EXPIRED", "detail": a["expires_at"]}
        if a["scope_hash"] != scope_hash(current_scope):
            return {"valid": False, "code": "SCOPE_MISMATCH", "detail": "repository, base commit, paths, actions, proposal or policy changed"}
        return {"valid": True, "code": "OK", "detail": None}

    def expire_due(self) -> int:
        now = iso(self.store.clock.now())
        with self.store.db.tx() as c:
            rows = c.execute("SELECT * FROM approvals WHERE status IN ('pending','approved') AND expires_at<=?", (now,)).fetchall()
            for a in rows:
                c.execute("UPDATE approvals SET status='expired' WHERE id=?", (a["id"],))
                self.store.emit("approval.expired", job_id=a["job_id"], repo_id=a["repo_id"], data={"approval_id": a["id"]})
            return len(rows)
