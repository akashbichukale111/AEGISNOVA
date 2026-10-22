"""Explicit job state machine. Invalid transitions are rejected; terminal states have no exits.

Stages (states) of the main pipeline::

    CREATED → QUEUED → VALIDATING → SNAPSHOTTING → INSPECTING → RESEARCHING → EVIDENCE_REVIEW
      → RISK_ASSESSMENT → (WAITING_FOR_APPROVAL →) READY_TO_EXECUTE → EXECUTING → TESTING
      → INDEPENDENT_VERIFICATION → COMPLETED | COMPLETED_WITH_WARNINGS | FAILED

Design notes
* Every attempt starts at VALIDATING (claim: QUEUED → VALIDATING). VALIDATING decides the resume point
  from the latest *valid* checkpoint, so resume logic lives in exactly one place.
* READY_TO_EXECUTE is the only door to EXECUTING (write-capable work). It re-validates base commit,
  approval scope/expiry/revocation, policy version and evidence freshness every time.
* A completed investigation (COMPLETED / COMPLETED_WITH_WARNINGS) never implies a repair happened:
  that is recorded separately in ``jobs.outcome`` (``repair_verified`` is the only repair success).
"""
from __future__ import annotations

from .errors import InvalidTransition

CREATED = "CREATED"
QUEUED = "QUEUED"
VALIDATING = "VALIDATING"
SNAPSHOTTING = "SNAPSHOTTING"
INSPECTING = "INSPECTING"
RESEARCHING = "RESEARCHING"
EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
RISK_ASSESSMENT = "RISK_ASSESSMENT"
WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
READY_TO_EXECUTE = "READY_TO_EXECUTE"
EXECUTING = "EXECUTING"
TESTING = "TESTING"
INDEPENDENT_VERIFICATION = "INDEPENDENT_VERIFICATION"
COMPLETED = "COMPLETED"
COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
FAILED = "FAILED"
RETRY_WAIT = "RETRY_WAIT"
PAUSED = "PAUSED"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"
DEAD_LETTER = "DEAD_LETTER"

ALL_STATES = [
    CREATED, QUEUED, VALIDATING, SNAPSHOTTING, INSPECTING, RESEARCHING, EVIDENCE_REVIEW, RISK_ASSESSMENT,
    WAITING_FOR_APPROVAL, READY_TO_EXECUTE, EXECUTING, TESTING, INDEPENDENT_VERIFICATION, COMPLETED,
    COMPLETED_WITH_WARNINGS, FAILED, RETRY_WAIT, PAUSED, CANCEL_REQUESTED, CANCELLED, EXPIRED, DEAD_LETTER,
]

# States in which a worker holds the lease and is doing work.
ACTIVE = frozenset(
    {VALIDATING, SNAPSHOTTING, INSPECTING, RESEARCHING, EVIDENCE_REVIEW, RISK_ASSESSMENT, READY_TO_EXECUTE,
     EXECUTING, TESTING, INDEPENDENT_VERIFICATION}
)
# CANCEL_REQUESTED may still be leased (a worker is winding down); every other state is unleased.
LEASE_HOLDING = ACTIVE | {CANCEL_REQUESTED}
TERMINAL = frozenset({COMPLETED, COMPLETED_WITH_WARNINGS, FAILED, CANCELLED, EXPIRED, DEAD_LETTER})
# Terminal states that count as "this job did what it was asked to do".
SUCCESS_TERMINAL = frozenset({COMPLETED, COMPLETED_WITH_WARNINGS})
# Write-capable stages: extra gate checks (approval still valid) apply here.
WRITE_STAGES = frozenset({READY_TO_EXECUTE, EXECUTING, TESTING, INDEPENDENT_VERIFICATION})
WAITING = frozenset({WAITING_FOR_APPROVAL, RETRY_WAIT, PAUSED})

_COMMON_ACTIVE_EXITS = {RETRY_WAIT, FAILED, DEAD_LETTER, PAUSED, CANCEL_REQUESTED, QUEUED, EXPIRED}

TRANSITIONS: dict[str, frozenset] = {
    CREATED: frozenset({QUEUED, CANCEL_REQUESTED}),
    QUEUED: frozenset({VALIDATING, PAUSED, CANCEL_REQUESTED, EXPIRED}),
    # Resume targets (decided from the latest valid checkpoint)
    VALIDATING: frozenset(
        {SNAPSHOTTING, INSPECTING, RESEARCHING, EVIDENCE_REVIEW, RISK_ASSESSMENT, READY_TO_EXECUTE} | _COMMON_ACTIVE_EXITS
    ),
    SNAPSHOTTING: frozenset({INSPECTING} | _COMMON_ACTIVE_EXITS),
    INSPECTING: frozenset({RESEARCHING} | _COMMON_ACTIVE_EXITS),
    RESEARCHING: frozenset({EVIDENCE_REVIEW} | _COMMON_ACTIVE_EXITS),
    EVIDENCE_REVIEW: frozenset({RISK_ASSESSMENT} | _COMMON_ACTIVE_EXITS),
    RISK_ASSESSMENT: frozenset(
        {WAITING_FOR_APPROVAL, READY_TO_EXECUTE, COMPLETED, COMPLETED_WITH_WARNINGS} | _COMMON_ACTIVE_EXITS
    ),
    WAITING_FOR_APPROVAL: frozenset({QUEUED, COMPLETED_WITH_WARNINGS, EXPIRED, PAUSED, CANCEL_REQUESTED}),
    # Gate: may bounce back for replan (changed base / policy / stale evidence) or wait for fresh approval.
    READY_TO_EXECUTE: frozenset(
        {EXECUTING, SNAPSHOTTING, RESEARCHING, RISK_ASSESSMENT, WAITING_FOR_APPROVAL, COMPLETED_WITH_WARNINGS}
        | _COMMON_ACTIVE_EXITS
    ),
    EXECUTING: frozenset({TESTING} | _COMMON_ACTIVE_EXITS),
    TESTING: frozenset({INDEPENDENT_VERIFICATION} | _COMMON_ACTIVE_EXITS),
    INDEPENDENT_VERIFICATION: frozenset({COMPLETED, COMPLETED_WITH_WARNINGS} | _COMMON_ACTIVE_EXITS),
    RETRY_WAIT: frozenset({QUEUED, DEAD_LETTER, CANCEL_REQUESTED, PAUSED, EXPIRED}),
    PAUSED: frozenset({QUEUED, CANCEL_REQUESTED, EXPIRED}),
    CANCEL_REQUESTED: frozenset({CANCELLED}),
    COMPLETED: frozenset(),
    COMPLETED_WITH_WARNINGS: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    EXPIRED: frozenset(),
    DEAD_LETTER: frozenset(),
}

assert set(TRANSITIONS) == set(ALL_STATES), "every state must define its exits"


def can_transition(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, frozenset())


def validate(frm: str, to: str) -> None:
    if frm not in TRANSITIONS:
        raise InvalidTransition(f"unknown state {frm!r}", code="UNKNOWN_STATE")
    if to not in TRANSITIONS:
        raise InvalidTransition(f"unknown target state {to!r}", code="UNKNOWN_STATE")
    if to not in TRANSITIONS[frm]:
        raise InvalidTransition(
            f"transition {frm} → {to} is not allowed", details={"from": frm, "to": to, "allowed": sorted(TRANSITIONS[frm])}
        )


def is_terminal(state: str) -> bool:
    return state in TERMINAL


# Ordered checkpoint stages; a later stage's checkpoint is invalid if an earlier one is redone.
STAGES = ["snapshot", "inspect", "research", "evidence_review", "risk", "proposal", "ready", "execute", "test", "verify"]
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}

# State to enter when resuming after a completed stage checkpoint.
RESUME_STATE = {
    None: SNAPSHOTTING,
    "snapshot": INSPECTING,
    "inspect": RESEARCHING,
    "research": EVIDENCE_REVIEW,
    "evidence_review": RISK_ASSESSMENT,
    "risk": RISK_ASSESSMENT,       # continues at proposal creation inside the risk handler
    "proposal": READY_TO_EXECUTE,  # the gate decides: wait for approval, replan, or execute
    "ready": READY_TO_EXECUTE,     # write-capable work ALWAYS re-passes the gate on resume
    "execute": READY_TO_EXECUTE,
    "test": READY_TO_EXECUTE,
    "verify": READY_TO_EXECUTE,
}
