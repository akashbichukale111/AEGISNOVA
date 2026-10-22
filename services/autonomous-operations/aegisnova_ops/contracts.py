"""Versioned contracts: enums, record schemas, strict validation.

Unknown fields are REJECTED (security-sensitive inputs must not be silently accepted).
"""
import re
from . import SCHEMA_VERSION


class ValidationError(ValueError):
    pass


class RunStatus:
    QUEUED = "QUEUED"; RUNNING = "RUNNING"; WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    RETRY_WAIT = "RETRY_WAIT"; PAUSED = "PAUSED"; SUCCEEDED = "SUCCEEDED"; FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"; CANCELLED = "CANCELLED"
    ALL = {QUEUED, RUNNING, WAITING_FOR_APPROVAL, RETRY_WAIT, PAUSED, SUCCEEDED, FAILED, DEAD_LETTERED, CANCELLED}
    TERMINAL = {SUCCEEDED, CANCELLED, FAILED, DEAD_LETTERED}


class Step:
    START = "START"; VALIDATE = "VALIDATE"; WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTE = "EXECUTE_SAFE_ACTION"; NOTIFY = "NOTIFY"; COMPLETE = "COMPLETE"
    ALL = [START, VALIDATE, WAITING_FOR_APPROVAL, EXECUTE, NOTIFY, COMPLETE]


class NotifStatus:
    CREATED = "CREATED"; QUEUED = "QUEUED"; SENDING = "SENDING"; ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"; RETRYING = "RETRYING"; FAILED = "FAILED"; SUPPRESSED = "SUPPRESSED"
    UNKNOWN = "UNKNOWN"; DEAD_LETTERED = "DEAD_LETTERED"
    ALL = {CREATED, QUEUED, SENDING, ACCEPTED, DELIVERED, RETRYING, FAILED, SUPPRESSED, UNKNOWN, DEAD_LETTERED}


APPROVAL_STATUSES = {"PENDING", "GRANTED", "REJECTED", "EXPIRED", "REVOKED"}
DECISIONS = {"granted", "rejected", "revoked"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
CHANNELS = {"local_sink", "email", "sms", "whatsapp"}
MODES = {"LOCAL", "SIMULATED", "REAL"}
QUEUE_STATUSES = {"VISIBLE", "IN_FLIGHT", "DONE", "DEAD"}
SEVERITIES = {"info", "warning", "critical"}
ALARM_STATES = {"OK", "ALARM", "UNAVAILABLE"}
INTEGRATION_STATES = {"CONFIGURED", "UNCONFIGURED", "LOCAL", "SIMULATED"}
ERROR_CLASSES = {"transient", "permanent", "timeout", "poison", "policy", "ambiguous",
                 "transient_exhausted", "approval_rejected", "approval_expired", "approval_revoked",
                 "validation", "unconfigured", "max_receive_exceeded"}

_TYPES = {
    "str": str, "int": int, "float": (int, float), "bool": bool, "dict": dict, "list": list,
}
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

# field spec: type name, optional "enum:<set>" handled via ENUMS, "id" = safe identifier, "iso" = timestamp
ENUMS = {"decision": DECISIONS, "risk": RISK_LEVELS, "channel": CHANNELS, "mode": MODES,
         "run_status": RunStatus.ALL, "notif_status": NotifStatus.ALL, "approval_status": APPROVAL_STATUSES,
         "severity": SEVERITIES, "alarm_state": ALARM_STATES, "integration_state": INTEGRATION_STATES,
         "queue_status": QUEUE_STATUSES}

_COMMON = {"id": "id", "schema_version": "str", "created_at": "iso"}

# Each schema: required fields and optional fields (name -> type spec).
SCHEMAS = {
    "WorkflowDefinition": {"req": {"name": "str", "version": "str", "steps": "list", "transitions": "dict",
                                   "schema_version": "str"}, "opt": {"description": "str"}},
    "WorkflowRun": {"req": {"id": "id", "schema_version": "str", "workflow_type": "str", "status": "enum:run_status",
                            "step": "str", "correlation_id": "id", "idempotency_key": "id", "tenant": "id",
                            "created_at": "iso", "updated_at": "iso"},
                    "opt": {"causation_id": "id", "approval_id": "id", "attempts": "int", "payload_hash": "str",
                            "failure_class": "str", "last_error": "str", "started_at": "iso", "finished_at": "iso",
                            "next_retry_at": "iso", "requires_approval": "bool", "payload": "dict",
                            "retry_started_at": "iso", "paused_from": "str", "cancel_reason": "str",
                            "attempt_base": "int"}},
    "WorkflowEvent": {"req": {"id": "id", "schema_version": "str", "entity_type": "str", "entity_id": "id",
                              "type": "str", "actor": "str", "ts": "iso"},
                      "opt": {"seq": "int", "run_id": "id", "from_state": "str", "to_state": "str", "step": "str",
                              "detail": "dict", "correlation_id": "id", "causation_id": "id"}},
    "ApprovalRequest": {"req": {"id": "id", "schema_version": "str", "run_id": "id", "action": "str", "scope": "str",
                                "risk_level": "enum:risk", "action_hash": "str", "expires_at": "iso",
                                "status": "enum:approval_status", "correlation_id": "id", "created_at": "iso"},
                        "opt": {"requester": "str", "reason": "str", "provider": "str", "provider_ref": "str",
                                "decided_at": "iso", "decision_ref": "str", "dev_only": "bool",
                                "blocked_reason": "str", "updated_at": "iso", "nonce": "str"}},
    # inbound decision envelope from the governance provider (strict)
    "ApprovalDecision": {"req": {"schema_version": "str", "event_id": "id", "issuer": "str", "audience": "str",
                                 "approval_id": "id", "run_id": "id", "action": "str", "scope": "str",
                                 "action_hash": "str", "decision": "enum:decision", "issued_at": "iso",
                                 "expires_at": "iso", "signature": "str"},
                         "opt": {"lineage_ref": "str"}},
    "NotificationRequest": {"req": {"channel": "enum:channel", "destination": "str"},
                            "opt": {"mode": "enum:mode", "template": "str", "idempotency_key": "id",
                                    "correlation_id": "id", "run_id": "id", "params": "dict"}},
    "NotificationAttempt": {"req": {"id": "id", "notification_id": "id", "attempt_no": "int", "started_at": "iso",
                                    "outcome": "str", "provider": "str"},
                            "opt": {"finished_at": "iso", "provider_message_id": "str", "error_class": "str",
                                    "error": "str", "correlation_id": "id", "schema_version": "str"}},
    "DeliveryReceipt": {"req": {"id": "id", "notification_id": "id", "provider": "str", "provider_event_id": "id",
                                "status": "str", "received_at": "iso", "verified": "bool", "source": "str"},
                        "opt": {"provider_ts": "str", "applied": "bool", "note": "str",
                                "provider_message_id": "str", "schema_version": "str"}},
    "QueueMessage": {"req": {"run_id": "id", "kind": "str"}, "opt": {"schema_version": "str", "approval_id": "id"}},
    "DeadLetterRecord": {"req": {"id": "id", "schema_version": "str", "kind": "str", "entity_id": "id",
                                 "payload_hash": "str", "error_class": "str", "status": "str", "created_at": "iso"},
                         "opt": {"queue_message_id": "id", "event_id": "id", "payload_ref": "str", "error": "str",
                                 "attempt_history": "list", "redriven_at": "iso", "redrive_count": "int",
                                 "correlation_id": "id"}},
    "OperationalMetric": {"req": {"name": "str", "value": "float", "ts": "iso", "source": "str"},
                          "opt": {"labels": "dict", "unit": "str"}},
    "AlarmDefinition": {"req": {"name": "str", "metric": "str", "comparison": "str", "threshold": "float",
                                "severity": "enum:severity", "runbook": "str"},
                        "opt": {"cooldown_s": "int", "description": "str", "unit": "str"}},
    "AlarmEvent": {"req": {"id": "id", "alarm_name": "str", "severity": "enum:severity", "state": "str",
                           "metric": "str", "threshold": "float", "triggered_at": "iso", "runbook": "str"},
                   "opt": {"value": "float", "resolved_at": "iso", "explanation": "str", "schema_version": "str"}},
    "ProviderHealth": {"req": {"provider": "str", "state": "str", "updated_at": "iso"},
                       "opt": {"consecutive_failures": "int", "cooldown_until": "iso", "last_error": "str",
                               "last_success_at": "iso", "last_failure_at": "iso", "opened_at": "iso"}},
    "IntegrationStatus": {"req": {"name": "str", "state": "enum:integration_state", "reason": "str"},
                          "opt": {"env_vars": "list", "kind": "str", "mode": "str", "checked_at": "iso",
                                  "setup": "str"}},
    # inbound request bodies
    "WorkflowStartRequest": {"req": {"workflow_type": "str", "payload": "dict"},
                             "opt": {"idempotency_key": "id", "correlation_id": "id", "tenant": "id",
                                     "causation_id": "id"}},
}


def _check_type(name, val, spec):
    if spec.startswith("enum:"):
        allowed = ENUMS[spec[5:]]
        if val not in allowed:
            raise ValidationError(f"{name}: must be one of {sorted(allowed)}")
        return
    if spec == "id":
        if not isinstance(val, str) or not _ID.match(val):
            raise ValidationError(f"{name}: invalid identifier")
        return
    if spec == "iso":
        if not isinstance(val, str) or not _ISO.match(val):
            raise ValidationError(f"{name}: invalid ISO-8601 UTC timestamp")
        return
    t = _TYPES[spec]
    if spec in ("int", "float") and isinstance(val, bool):
        raise ValidationError(f"{name}: expected {spec}")
    if not isinstance(val, t):
        raise ValidationError(f"{name}: expected {spec}")


def validate(schema_name, data, allow_none_optional=True):
    """Strict validation. Returns a shallow copy. Raises ValidationError on unknown/missing/malformed."""
    schema = SCHEMAS[schema_name]
    if not isinstance(data, dict):
        raise ValidationError("body must be a JSON object")
    allowed = set(schema["req"]) | set(schema["opt"])
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"unknown field(s): {sorted(unknown)}")
    for k, spec in schema["req"].items():
        if k not in data or data[k] is None:
            raise ValidationError(f"missing required field: {k}")
        _check_type(k, data[k], spec)
    for k, spec in schema["opt"].items():
        if k in data and data[k] is not None:
            _check_type(k, data[k], spec)
    return dict(data)


def to_contract(schema_name, row):
    """Project a DB row (dict) onto a contract: drop internal fields, parse JSON-ish ones, drop Nones."""
    schema = SCHEMAS[schema_name]
    allowed = set(schema["req"]) | set(schema["opt"])
    out = {}
    for k, v in row.items():
        if k in allowed and v is not None:
            out[k] = bool(v) if schema["req"].get(k, schema["opt"].get(k)) == "bool" else v
    out.setdefault("schema_version", SCHEMA_VERSION) if "schema_version" in allowed else None
    return out


# ---- Sample workflow ---------------------------------------------------------------

ALLOWED_ACTIONS = {"record_marker"}   # bounded autonomy: only this safe, idempotent action exists

WORKFLOW_DEFINITIONS = {
    "sample.governed_action": {
        "schema_version": SCHEMA_VERSION, "name": "sample.governed_action", "version": "1",
        "description": "START -> VALIDATE -> (approval) -> EXECUTE_SAFE_ACTION -> NOTIFY -> COMPLETE",
        "steps": ["START", "VALIDATE", "WAITING_FOR_APPROVAL", "EXECUTE_SAFE_ACTION", "NOTIFY", "COMPLETE"],
        "transitions": {"START": ["VALIDATE"], "VALIDATE": ["WAITING_FOR_APPROVAL", "EXECUTE_SAFE_ACTION"],
                        "WAITING_FOR_APPROVAL": ["EXECUTE_SAFE_ACTION"], "EXECUTE_SAFE_ACTION": ["NOTIFY"],
                        "NOTIFY": ["COMPLETE"], "COMPLETE": []},
    }
}

_PAYLOAD_KEYS = {"action", "scope", "risk_level", "reason", "requester", "approval_required", "notify",
                 "simulate", "approval_ttl_s", "marker"}


def validate_sample_payload(p):
    if not isinstance(p, dict):
        raise ValidationError("payload must be an object")
    unknown = set(p) - _PAYLOAD_KEYS
    if unknown:
        raise ValidationError(f"unknown payload field(s): {sorted(unknown)}")
    out = {
        "action": p.get("action", "record_marker"),
        "scope": p.get("scope", "ops:record_marker"),
        "risk_level": p.get("risk_level", "low"),
        "reason": str(p.get("reason", ""))[:500],
        "requester": str(p.get("requester", "operator"))[:120],
        "approval_required": p.get("approval_required", True),
        "marker": str(p.get("marker", "sample"))[:120],
        "approval_ttl_s": p.get("approval_ttl_s", 3600),
    }
    if out["action"] not in ALLOWED_ACTIONS:
        raise ValidationError(f"action not allowed; allowed: {sorted(ALLOWED_ACTIONS)}")
    if not re.match(r"^[a-z0-9_.:-]{1,80}$", out["scope"]):
        raise ValidationError("scope: invalid format")
    if out["risk_level"] not in RISK_LEVELS:
        raise ValidationError("risk_level invalid")
    if not isinstance(out["approval_required"], bool):
        raise ValidationError("approval_required must be boolean")
    ttl = out["approval_ttl_s"]
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not (1 <= ttl <= 7 * 86400):
        raise ValidationError("approval_ttl_s must be 1..604800")
    notify = p.get("notify") or {"channel": "local_sink", "destination": "ops-sink@local.test", "mode": "LOCAL"}
    if not isinstance(notify, dict) or set(notify) - {"channel", "destination", "mode"}:
        raise ValidationError("notify: unknown fields")
    notify = {"channel": notify.get("channel", "local_sink"), "destination": notify.get("destination", "ops-sink@local.test"),
              "mode": notify.get("mode", "LOCAL")}
    if notify["channel"] not in CHANNELS:
        raise ValidationError("notify.channel invalid")
    if notify["mode"] not in ("LOCAL", "SIMULATED"):
        raise ValidationError("workflows may only notify in LOCAL or SIMULATED mode; real sends are user-triggered")
    if not isinstance(notify["destination"], str) or not (3 <= len(notify["destination"]) <= 200):
        raise ValidationError("notify.destination invalid")
    out["notify"] = notify
    sim = p.get("simulate") or {}
    if not isinstance(sim, dict) or set(sim) - {"fail_times", "kind", "slow_s"}:
        raise ValidationError("simulate: unknown fields")
    sim = {"fail_times": sim.get("fail_times", 0), "kind": sim.get("kind", "transient"), "slow_s": sim.get("slow_s", 0)}
    if not (isinstance(sim["fail_times"], int) and 0 <= sim["fail_times"] <= 20) or sim["kind"] not in ("transient", "permanent"):
        raise ValidationError("simulate invalid")
    if not isinstance(sim["slow_s"], (int, float)) or sim["slow_s"] < 0:
        raise ValidationError("simulate.slow_s invalid")
    out["simulate"] = sim
    return out
