"""Governance boundary. UNWIND is the authority for approvals; this module only
(a) defines the provider contract, (b) verifies decision envelopes fail-closed, and
(c) offers a clearly labelled LOCAL DEVELOPMENT provider that is NEVER production governance."""
import hashlib
import hmac
import os
from datetime import timedelta

from . import SCHEMA_VERSION
from .clock import iso, parse_iso
from .util import canonical, new_id, validate_https_url, redact

AUDIENCE = "aegisnova-ops"
LOCAL_ISSUER = "aegisnova-local-dev-governance"
MAX_SKEW_S = 120
MAX_DECISION_AGE_S = 900


class DecisionRejected(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def sign_envelope(env, key):
    body = {k: v for k, v in env.items() if k != "signature"}
    return hmac.new(key.encode(), canonical(body).encode(), hashlib.sha256).hexdigest()


def compute_action_hash(action, scope, params):
    return hashlib.sha256(canonical({"action": action, "scope": scope, "params": params}).encode()).hexdigest()


def verify_envelope(env, approval, now, key, issuer, audience=AUDIENCE):
    """Validate a (schema-checked) decision envelope against the approval row. Raises DecisionRejected."""
    if not key:
        raise DecisionRejected("governance_unconfigured", "no verification key")
    expected = sign_envelope(env, key)
    if not hmac.compare_digest(expected, str(env.get("signature", ""))):
        raise DecisionRejected("bad_signature")
    if env["issuer"] != issuer:
        raise DecisionRejected("bad_issuer")
    if env["audience"] != audience:
        raise DecisionRejected("bad_audience")
    if env["schema_version"] != SCHEMA_VERSION:
        raise DecisionRejected("unsupported_schema_version")
    issued, exp = parse_iso(env["issued_at"]), parse_iso(env["expires_at"])
    if issued > now + timedelta(seconds=MAX_SKEW_S):
        raise DecisionRejected("issued_in_future")
    if now - issued > timedelta(seconds=MAX_DECISION_AGE_S):
        raise DecisionRejected("decision_too_old")
    if exp <= now:
        raise DecisionRejected("decision_expired")
    for f in ("approval_id", "run_id", "action", "scope", "action_hash"):
        bound = approval["id"] if f == "approval_id" else approval[f]
        if env[f] != bound:
            raise DecisionRejected("binding_mismatch", f)
    return {"event_id": env["event_id"], "decision": env["decision"], "lineage_ref": env.get("lineage_ref"),
            "issuer": env["issuer"]}


class GovernanceProvider:
    name = "abstract"
    is_production = False

    def configured(self):
        raise NotImplementedError

    def status_reason(self):
        return ""

    def create_request(self, approval):
        """Register the approval request with the authority. Returns provider_ref."""
        raise NotImplementedError

    def verify_decision(self, env, approval, now):
        raise NotImplementedError

    def fetch_decision(self, approval):
        """Authenticated polling (optional). Return raw envelope dict or None."""
        return None


class LocalDevGovernance(GovernanceProvider):
    """TEST-ONLY. Signs and verifies with a local dev key. Not production authorization."""
    name = "local-dev"
    is_production = False

    def __init__(self, key=None):
        self.key = key or os.environ.get("AEGIS_LOCAL_DEV_GOVERNANCE_KEY", "local-dev-only-not-a-secret")

    def configured(self):
        return True

    def status_reason(self):
        return "LOCAL DEVELOPMENT governance: decisions are test-only and are not production authorization."

    def create_request(self, approval):
        return f"local-dev:{approval['id']}"

    def issue_decision(self, approval, decision, now, ttl_s=300, event_id=None):
        env = {"schema_version": SCHEMA_VERSION, "event_id": event_id or new_id("evt"), "issuer": LOCAL_ISSUER,
               "audience": AUDIENCE, "approval_id": approval["id"], "run_id": approval["run_id"],
               "action": approval["action"], "scope": approval["scope"], "action_hash": approval["action_hash"],
               "decision": decision, "issued_at": iso(now), "expires_at": iso(now + timedelta(seconds=ttl_s)),
               "lineage_ref": f"local-dev-lineage:{approval['id']}"}
        env["signature"] = sign_envelope(env, self.key)
        return env

    def verify_decision(self, env, approval, now):
        return verify_envelope(env, approval, now, self.key, LOCAL_ISSUER)


class UnwindAdapter(GovernanceProvider):
    """Adapter to UNWIND (the authoritative governance core). Stays UNCONFIGURED until env is supplied.

    The wire contract here is the *integration contract* documented in GOVERNANCE_AND_APPROVALS.md;
    it has NOT been exercised against a live UNWIND instance."""
    name = "unwind"
    is_production = True
    ENV = ["UNWIND_BASE_URL", "UNWIND_API_TOKEN", "UNWIND_ISSUER", "UNWIND_SIGNING_KEY"]

    def __init__(self, env=None, http=None):
        env = os.environ if env is None else env
        self.base = env.get("UNWIND_BASE_URL", "")
        self.token = env.get("UNWIND_API_TOKEN", "")
        self.issuer = env.get("UNWIND_ISSUER", "")
        self.key = env.get("UNWIND_SIGNING_KEY", "")
        self.http = http
        self._err = None
        if self.base:
            try:
                validate_https_url(self.base)
            except ValueError as e:
                self._err = f"UNWIND_BASE_URL rejected: {e}"

    def configured(self):
        return all([self.base, self.token, self.issuer, self.key]) and not self._err

    def status_reason(self):
        if self._err:
            return self._err
        missing = [n for n, v in zip(self.ENV, [self.base, self.token, self.issuer, self.key]) if not v]
        return ("missing env: " + ", ".join(missing)) if missing else "configured (contract untested against a live UNWIND)"

    def create_request(self, approval):
        if not self.configured():
            raise DecisionRejected("governance_unconfigured", self.status_reason())
        if self.http is None:
            raise DecisionRejected("governance_unconfigured", "no HTTP client wired")
        body = {"approval_id": approval["id"], "run_id": approval["run_id"], "action": approval["action"],
                "scope": approval["scope"], "risk_level": approval["risk_level"], "action_hash": approval["action_hash"],
                "expires_at": approval["expires_at"], "correlation_id": approval["correlation_id"]}
        status, data = self.http("POST", self.base.rstrip("/") + "/v1/approvals",
                                 {"Authorization": f"Bearer {self.token}"}, body)
        if status >= 300 or not isinstance(data, dict) or "ref" not in data:
            raise DecisionRejected("governance_request_failed", redact(f"status {status}"))
        return str(data["ref"])

    def verify_decision(self, env, approval, now):
        return verify_envelope(env, approval, now, self.key, self.issuer)

    def fetch_decision(self, approval):
        if not (self.configured() and self.http):
            return None
        status, data = self.http("GET", self.base.rstrip("/") + f"/v1/approvals/{approval['id']}/decision",
                                 {"Authorization": f"Bearer {self.token}"}, None)
        return data if status == 200 and isinstance(data, dict) else None


def select_provider(env=None, http=None):
    env = os.environ if env is None else env
    if env.get("AEGIS_GOVERNANCE", "local").lower() == "unwind":
        return UnwindAdapter(env, http)
    return LocalDevGovernance()
