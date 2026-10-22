"""Shared test helpers. EVERYTHING created here is TEST DATA (synthetic repositories, synthetic advisories, a fake clock)."""
from __future__ import annotations

import json
import random
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from nightshift.config import Settings
from nightshift.demo import FIXTURES, seed_demo
from nightshift.service import App, Principal
from nightshift.util import FakeClock, iso
from nightshift.worker import Worker

ADMIN = Principal("alice-admin", "admin")
OPERATOR = Principal("oscar-operator", "operator")
APPROVER = Principal("bob-approver", "approver")
VIEWER = Principal("vera-viewer", "viewer")


class Env:
    """Self-contained NightShift instance in a temp dir with a deterministic clock and the synthetic demo fixtures."""

    def __init__(self, *, env: dict | None = None, providers=None, seed: bool = True, clock: FakeClock | None = None, transport=None,
                 policy_env_tokens: bool = True):
        self.tmp = tempfile.TemporaryDirectory(prefix="nsd-test-")
        base = {"NIGHTSHIFT_DATA_DIR": self.tmp.name, "NIGHTSHIFT_SANDBOX_REQUIRE_NETNS": "0", "NIGHTSHIFT_LEASE_SECONDS": "60",
                "NIGHTSHIFT_RETRY_BASE_SECONDS": "5", "NIGHTSHIFT_RETRY_MAX_ATTEMPTS": "4", "NIGHTSHIFT_SANDBOX_TIMEOUT_SECONDS": "60",
                "NIGHTSHIFT_ADMIN_TOKEN": "test-admin-token-not-a-secret", "NIGHTSHIFT_OPERATOR_TOKEN": "test-operator-token-not-a-secret",
                "NIGHTSHIFT_APPROVER_TOKEN": "test-approver-token-not-a-secret", "NIGHTSHIFT_VIEWER_TOKEN": "test-viewer-token-not-a-secret",
                "NIGHTSHIFT_TOKENS_FILE": str(Path(self.tmp.name) / "no-tokens.json")}
        base.update(env or {})
        self.settings = Settings.from_env(base)
        self.clock = clock or FakeClock()
        self.app = App(self.settings, clock=self.clock, rng=random.Random(7), providers=providers, transport=transport)
        if seed:
            seed_demo(self.app, ADMIN, with_schedule=False)
        self.workers: list[Worker] = []

    # -- conveniences
    @property
    def store(self):
        return self.app.store

    def repo(self, slug: str) -> dict:
        return self.store.get_repo_by_slug(slug if "/" in slug else f"demo/{slug}")

    def repo_path(self, slug: str) -> Path:
        return Path(self.settings.repo_root) / "demo" / slug

    def worker(self, **kw) -> Worker:
        a = self.app
        kw.setdefault("heartbeat_thread", False)
        w = Worker(a.store, a.settings, a.runner, a.gov, a.sandbox, a.notifier, **kw)
        self.workers.append(w)
        return w

    def trigger(self, slug: str, *, allow_repair: bool = False, principal: Principal = ADMIN, key: str | None = None):
        job, _ = self.app.trigger(principal, self.repo(slug)["id"], allow_repair=allow_repair, idempotency_key=key)
        return job

    def job(self, job_id: str) -> dict:
        return self.store.get_job(job_id)

    def transitions(self, job_id: str) -> list[str]:
        return [f"{t['from_state']}>{t['to_state']}:{t['reason_code']}" for t in self.store.list_transitions(job_id)]

    def reasons(self, job_id: str) -> list[str]:
        return [t["reason_code"] for t in self.store.list_transitions(job_id)]

    def run(self, worker: Worker | None = None, n: int = 1):
        w = worker or self.worker()
        last = None
        for _ in range(n):
            last = w.run_once()
        return last

    def drain(self, worker: Worker | None = None, limit: int = 12):
        w = worker or self.worker()
        for _ in range(limit):
            if w.run_once() is None:
                break

    def pending_approval(self, job_id: str) -> dict | None:
        r = self.app.db.read().execute("SELECT * FROM approvals WHERE job_id=? AND status='pending' ORDER BY requested_at DESC", (job_id,)).fetchone()
        return dict(r) if r else None

    def approve(self, job_id: str, who: Principal = APPROVER) -> dict:
        a = self.pending_approval(job_id)
        assert a, "no pending approval"
        return self.app.decide_approval(who, a["id"], "approve", "test approval")

    def to_waiting(self, slug: str = "payments-service", **kw) -> dict:
        job = self.trigger(slug, allow_repair=True)
        self.run(**kw)
        assert self.job(job["id"])["state"] == "WAITING_FOR_APPROVAL", self.job(job["id"])["state"]
        return job

    def tree_snapshot(self, slug: str) -> dict:
        root = self.repo_path(slug)
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}

    def write_advisories(self, name: str, advisories: list, *, age_days: float = 0, label: str = "TEST DATA") -> None:
        path = self.settings.advisory_file if name == "primary" else self.settings.advisory_file_secondary
        Path(path).write_text(json.dumps({"generated_at": iso(self.clock.now() - timedelta(days=age_days)), "label": label, "advisories": advisories}))

    def make_repo(self, slug: str, files: dict, *, allow_repair=True, test_command_key="python-unittest", policy="default") -> dict:
        root = Path(self.settings.repo_root) / "demo" / slug
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return self.app.register_repo(ADMIN, {"name": slug, "slug": f"demo/{slug}", "rel_path": f"demo/{slug}", "allow_repair": allow_repair,
                                              "test_command_key": test_command_key, "policy_name": policy, "is_demo": True})

    def close(self):
        self.app.db.close()
        self.tmp.cleanup()


def adv(id_, package, fixed, *, eco="PyPI", severity="HIGH", introduced="0"):
    rng = {"introduced": introduced}
    if fixed:
        rng["fixed"] = fixed
    return {"id": id_, "ecosystem": eco, "package": package, "severity": severity, "summary": f"TEST DATA advisory {id_}",
            "url": f"https://example.invalid/{id_}", "ranges": [rng]}


PASSING_TESTS = "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
