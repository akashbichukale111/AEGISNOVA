"""Configuration, loaded from environment variables (see .env.example).

No secret value is ever logged. Dev tokens are generated locally by ``init`` into a
0600 file inside the data directory and are never part of the source tree or the ZIP.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from .redact import REDACTOR

ROLES = ("viewer", "operator", "approver", "admin")
# Permission model (explicit capability sets, not a linear rank):
PERMISSIONS = {
    "read": {"viewer", "operator", "approver", "admin"},
    "operate": {"operator", "admin"},
    "approve": {"approver", "admin"},
    "authorize_repair": {"approver", "admin"},  # may request WRITE-capable (repair) work; approval is still separate
    "admin": {"admin"},
}


def _bool(env, key, default):
    v = env.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(env, key, default):
    try:
        return int(env.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8787
    mode: str = "local"  # explicit execution mode label shown in the UI
    repo_root: Path | None = None
    workspaces_dir: Path | None = None
    db_path: Path | None = None
    tokens_file: Path | None = None
    advisory_file: Path | None = None
    advisory_file_secondary: Path | None = None
    osv_enabled: bool = False
    osv_url: str = "https://api.osv.dev/v1/query"
    evidence_max_age_seconds: int = 7 * 86400
    lease_seconds: int = 60
    scheduler_tick_seconds: float = 5.0
    watchdog_interval_seconds: float = 15.0
    worker_poll_seconds: float = 1.0
    stage_timeout_seconds: int = 300
    job_max_duration_seconds: int = 3600
    queue_cap_per_repo: int = 25
    approval_ttl_seconds: int = 24 * 3600
    max_replans: int = 3
    require_separation_of_duties: bool = True
    sandbox_require_netns: bool = True
    sandbox_timeout_seconds: int = 120
    sandbox_memory_bytes: int = 1024 * 1024 * 1024
    sandbox_output_cap_bytes: int = 256 * 1024
    max_body_bytes: int = 256 * 1024
    rate_limit_per_minute: int = 240
    trigger_rate_limit_per_minute: int = 20
    webhook_secret: str | None = None
    notify_webhook_url: str | None = None
    # retry defaults
    retry_max_attempts: int = 4
    retry_base_seconds: float = 5.0
    retry_max_seconds: float = 300.0
    retry_max_elapsed_seconds: float = 3600.0
    # watchdog thresholds
    queue_age_alert_seconds: int = 900
    queue_depth_alert: int = 50
    dlq_alert_count: int = 3
    stale_checkpoint_seconds: int = 1800
    progress_stall_seconds: int = 300
    provider_failure_alert: int = 3
    notification_stuck_seconds: int = 600
    tokens: dict = field(default_factory=dict)  # sha256(token) -> (actor, role)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        data_dir = Path(env.get("NIGHTSHIFT_DATA_DIR", "./data")).expanduser().resolve()
        s = cls(data_dir=data_dir)
        s.host = env.get("NIGHTSHIFT_HOST", s.host)
        s.port = _int(env, "NIGHTSHIFT_PORT", s.port)
        s.mode = env.get("NIGHTSHIFT_MODE", s.mode)
        s.repo_root = Path(env.get("NIGHTSHIFT_REPO_ROOT", data_dir / "repos")).expanduser().resolve()
        s.workspaces_dir = Path(env.get("NIGHTSHIFT_WORKSPACES_DIR", data_dir / "workspaces")).expanduser().resolve()
        s.db_path = Path(env.get("NIGHTSHIFT_DB_PATH", data_dir / "nightshift.db")).expanduser().resolve()
        s.tokens_file = Path(env.get("NIGHTSHIFT_TOKENS_FILE", data_dir / "local-tokens.json")).expanduser().resolve()
        s.advisory_file = Path(
            env.get("NIGHTSHIFT_ADVISORY_FILE", data_dir / "advisories" / "local-advisories.json")
        ).expanduser().resolve()
        s.advisory_file_secondary = Path(
            env.get("NIGHTSHIFT_ADVISORY_FILE_SECONDARY", data_dir / "advisories" / "local-advisories-secondary.json")).expanduser().resolve()
        s.osv_enabled = _bool(env, "NIGHTSHIFT_OSV_ENABLED", s.osv_enabled)
        s.osv_url = env.get("NIGHTSHIFT_OSV_URL", s.osv_url)
        s.evidence_max_age_seconds = _int(env, "NIGHTSHIFT_EVIDENCE_MAX_AGE_SECONDS", s.evidence_max_age_seconds)
        s.lease_seconds = _int(env, "NIGHTSHIFT_LEASE_SECONDS", s.lease_seconds)
        s.scheduler_tick_seconds = float(env.get("NIGHTSHIFT_SCHEDULER_TICK_SECONDS", s.scheduler_tick_seconds))
        s.watchdog_interval_seconds = float(env.get("NIGHTSHIFT_WATCHDOG_INTERVAL_SECONDS", s.watchdog_interval_seconds))
        s.worker_poll_seconds = float(env.get("NIGHTSHIFT_WORKER_POLL_SECONDS", s.worker_poll_seconds))
        s.stage_timeout_seconds = _int(env, "NIGHTSHIFT_STAGE_TIMEOUT_SECONDS", s.stage_timeout_seconds)
        s.job_max_duration_seconds = _int(env, "NIGHTSHIFT_JOB_MAX_DURATION_SECONDS", s.job_max_duration_seconds)
        s.queue_cap_per_repo = _int(env, "NIGHTSHIFT_QUEUE_CAP_PER_REPO", s.queue_cap_per_repo)
        s.approval_ttl_seconds = _int(env, "NIGHTSHIFT_APPROVAL_TTL_SECONDS", s.approval_ttl_seconds)
        s.require_separation_of_duties = _bool(env, "NIGHTSHIFT_SEPARATION_OF_DUTIES", s.require_separation_of_duties)
        s.sandbox_require_netns = _bool(env, "NIGHTSHIFT_SANDBOX_REQUIRE_NETNS", s.sandbox_require_netns)
        s.sandbox_timeout_seconds = _int(env, "NIGHTSHIFT_SANDBOX_TIMEOUT_SECONDS", s.sandbox_timeout_seconds)
        s.rate_limit_per_minute = _int(env, "NIGHTSHIFT_RATE_LIMIT_PER_MINUTE", s.rate_limit_per_minute)
        s.trigger_rate_limit_per_minute = _int(env, "NIGHTSHIFT_TRIGGER_RATE_LIMIT_PER_MINUTE", s.trigger_rate_limit_per_minute)
        s.webhook_secret = env.get("NIGHTSHIFT_WEBHOOK_SECRET") or None
        s.notify_webhook_url = env.get("NIGHTSHIFT_NOTIFY_WEBHOOK_URL") or None
        s.retry_max_attempts = _int(env, "NIGHTSHIFT_RETRY_MAX_ATTEMPTS", s.retry_max_attempts)
        s.retry_base_seconds = float(env.get("NIGHTSHIFT_RETRY_BASE_SECONDS", s.retry_base_seconds))
        s.retry_max_seconds = float(env.get("NIGHTSHIFT_RETRY_MAX_SECONDS", s.retry_max_seconds))
        s.retry_max_elapsed_seconds = float(env.get("NIGHTSHIFT_RETRY_MAX_ELAPSED_SECONDS", s.retry_max_elapsed_seconds))
        REDACTOR.register(s.webhook_secret)
        s.load_tokens(env)
        return s

    # ---- tokens -------------------------------------------------------------------------
    def load_tokens(self, env=None) -> None:
        env = os.environ if env is None else env
        raw: dict[str, tuple[str, str]] = {}
        if self.tokens_file and Path(self.tokens_file).exists():
            try:
                data = json.loads(Path(self.tokens_file).read_text())
                for role, entry in data.items():
                    if role in ROLES and entry.get("token"):
                        raw[entry["token"]] = (entry.get("actor", f"local-{role}"), role)
            except (OSError, ValueError):
                pass
        for role in ROLES:
            tok = env.get(f"NIGHTSHIFT_{role.upper()}_TOKEN")
            if tok:
                raw[tok] = (env.get(f"NIGHTSHIFT_{role.upper()}_ACTOR", f"env-{role}"), role)
        import hashlib

        self.tokens = {}
        for tok, ident in raw.items():
            REDACTOR.register(tok)
            self.tokens[hashlib.sha256(tok.encode()).hexdigest()] = ident

    def authenticate(self, token: str | None):
        """Return (actor, role) for a bearer token, using constant-time comparison."""
        if not token:
            return None
        import hashlib

        digest = hashlib.sha256(token.encode()).hexdigest()
        found = None
        for known, ident in self.tokens.items():
            if hmac.compare_digest(known, digest):
                found = ident
        return found

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.repo_root, self.workspaces_dir, self.advisory_file.parent):
            Path(p).mkdir(parents=True, exist_ok=True)

    def generate_dev_tokens(self) -> bool:
        """Create a 0600 token file for local development if missing. Returns True if created."""
        if self.tokens_file.exists():
            return False
        self.tokens_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            role: {"actor": f"local-{role}", "token": "nsd_" + secrets.token_urlsafe(24)} for role in ROLES
        }
        fd = os.open(self.tokens_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        self.load_tokens()
        return True

    def public_view(self) -> dict:
        """Redacted configuration summary (never contains secret values)."""
        return {
            "mode": self.mode,
            "host": self.host,
            "port": self.port,
            "lease_seconds": self.lease_seconds,
            "evidence_max_age_seconds": self.evidence_max_age_seconds,
            "sandbox_require_netns": self.sandbox_require_netns,
            "require_separation_of_duties": self.require_separation_of_duties,
            "webhook_secret": "configured" if self.webhook_secret else "not configured",
            "notify_webhook": "configured" if self.notify_webhook_url else "not configured",
            "osv_enabled": self.osv_enabled,
            "tokens_configured": len(self.tokens),
        }
