"""Bounded, observable retry policy: exponential backoff with jitter and error classification."""
from __future__ import annotations

import random
import socket
import urllib.error

from .errors import PermanentError, TransientError

DEFAULT_RETRY_POLICY = {
    "max_attempts": 4,          # failed attempts allowed before DEAD_LETTER
    "base_seconds": 5.0,
    "max_seconds": 300.0,       # cap for a single backoff delay
    "max_elapsed_seconds": 3600.0,  # total retry window measured from first start
}


def normalize_policy(p: dict | None, defaults: dict | None = None) -> dict:
    base = dict(DEFAULT_RETRY_POLICY)
    if defaults:
        base.update(defaults)
    if p:
        base.update({k: p[k] for k in DEFAULT_RETRY_POLICY if k in p})
    return base


def validate_policy(p: dict) -> list[str]:
    errs = []
    if not isinstance(p.get("max_attempts"), int) or not 1 <= p["max_attempts"] <= 10:
        errs.append("max_attempts must be an integer between 1 and 10")
    for k, lo, hi in (("base_seconds", 0.0, 3600.0), ("max_seconds", 0.0, 86400.0), ("max_elapsed_seconds", 1.0, 7 * 86400.0)):
        v = p.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
            errs.append(f"{k} must be a number between {lo} and {hi}")
    if not errs and p["base_seconds"] > p["max_seconds"]:
        errs.append("base_seconds must not exceed max_seconds")
    return errs


def compute_delay(failed_attempts: int, policy: dict, *, retry_after: float | None = None, rng: random.Random | None = None) -> float:
    """Equal-jitter exponential backoff.

    ``ceiling = min(max_seconds, base * 2**(n-1))``; delay is uniform in ``[ceiling/2, ceiling]``.
    A provider ``Retry-After`` raises the floor but the result never exceeds ``max_seconds``.
    """
    rng = rng or random
    n = max(1, failed_attempts)
    ceiling = min(float(policy["max_seconds"]), float(policy["base_seconds"]) * (2 ** (n - 1)))
    delay = ceiling / 2.0 + rng.uniform(0.0, ceiling / 2.0)
    if retry_after is not None and retry_after > 0:
        delay = max(delay, float(retry_after))
    return min(delay, float(policy["max_seconds"]))


def classify_http_status(status: int, retry_after: float | None = None):
    """Map a provider HTTP status to a retry decision. Returns an exception instance."""
    if status == 429:
        return TransientError("PROVIDER_RATE_LIMITED", "provider rate limit", retry_after=retry_after)
    if status in (408, 425) or 500 <= status <= 599:
        return TransientError("PROVIDER_UNAVAILABLE", f"provider returned HTTP {status}")
    if status in (401, 403):
        return PermanentError("PROVIDER_AUTH_FAILED", f"provider rejected credentials (HTTP {status})")
    return PermanentError("PROVIDER_BAD_REQUEST", f"provider returned HTTP {status}")


def classify_exception(exc: BaseException):
    """Return ('transient'|'permanent', code, retry_after). Unknown exceptions are treated as transient
    (bounded by the retry budget) so a one-off bug cannot permanently wedge a job silently."""
    if isinstance(exc, TransientError):
        return "transient", exc.code, exc.retry_after
    if isinstance(exc, PermanentError):
        return "permanent", exc.code, None
    if isinstance(exc, urllib.error.HTTPError):
        mapped = classify_http_status(exc.code)
        kind = "transient" if isinstance(mapped, TransientError) else "permanent"
        return kind, mapped.code, getattr(mapped, "retry_after", None)
    if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError)):
        return "transient", "PROVIDER_UNAVAILABLE", None
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "permanent", "INVALID_DATA", None
    return "transient", "INTERNAL_ERROR", None


RECOVERY_HINTS = {
    "PROVIDER_RATE_LIMITED": "Wait for the provider rate limit window; the job retries automatically with backoff.",
    "PROVIDER_UNAVAILABLE": "Provider outage or network failure; automatic retry is scheduled. Check Settings → Provider health.",
    "PROVIDER_AUTH_FAILED": "Credentials were rejected. Fix provider credentials, then replay the job. No automatic retry.",
    "PROVIDER_BAD_REQUEST": "Provider rejected the request as malformed. Inspect the evidence and replay after fixing input.",
    "POLICY_DENIED": "Policy denied this action. Change the policy or request via an authorised path; retries cannot bypass policy.",
    "APPROVAL_EXPIRED": "Approval expired. Request a fresh approval by replaying the job.",
    "APPROVAL_REVOKED": "Approval was revoked by a human. The repair will not proceed; replay to request a new approval.",
    "REGRESSION_TESTS_FAILED": "The regression gate failed with the proposed change. No repair was applied; review the test log.",
    "VERIFIER_DISAGREEMENT": "The independent verifier disagreed with the executor. Review the verifier report before any retry.",
    "LEASE_EXPIRED": "The worker stopped reporting progress. The job resumes from its last valid checkpoint.",
    "RETRIES_EXHAUSTED": "Retry budget exhausted. Diagnose the underlying error, then replay the job (creates a linked replay job).",
    "RETRY_WINDOW_EXCEEDED": "Retry window exceeded. Diagnose the underlying error, then replay the job.",
    "JOB_DEADLINE_EXCEEDED": "The job exceeded its maximum duration. Increase the schedule's max duration or investigate slow stages.",
    "INTERNAL_ERROR": "Unexpected internal error; retried within the bounded budget. If it persists, inspect the structured error.",
    "INVALID_DATA": "Input data was malformed. Fix the repository content or configuration and replay.",
    "SANDBOX_UNSAFE": "No safe sandbox is available on this host. Repairs are blocked (fail closed). See Settings → Provider health.",
    "REPO_UNAVAILABLE": "Repository path is missing or invalid. Fix the repository registration, then replay.",
    "REPLAN_LIMIT_EXCEEDED": "The repository kept changing underneath the job. Wait for it to settle, then replay.",
    "NO_ADVISORY_PROVIDER": "No advisory provider is configured. Provide an advisory snapshot or enable OSV, then replay.",
    "REPO_TOO_LARGE": "Repository exceeds snapshot limits. Narrow the registered path or raise limits deliberately.",
    "STAGE_TIMEOUT": "A stage exceeded its time budget; the job retries from its last checkpoint within the retry budget.",
    "BASELINE_TESTS_FAILING": "The unmodified repository already fails its regression gate, so a repair cannot be attributed. Fix the baseline first.",
    "REPAIR_NOT_AUTHORIZED": "Write-capable repair is not authorised for this job/repository.",
}


def recovery_hint(code: str) -> str:
    return RECOVERY_HINTS.get(code, "Inspect the structured error and job history; replay if the cause is resolved.")
