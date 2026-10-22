"""Error taxonomy.

* ``NightShiftError`` subclasses map to HTTP responses (consistent error format).
* ``TransientError`` / ``PermanentError`` drive retry behaviour in the worker.
* ``WorkflowSignal`` subclasses are control-flow signals (cancel/pause/replan).
* ``SimulatedCrash`` derives from BaseException so *no* handler in the worker
  swallows it; tests use it to emulate a process dying mid-stage.
"""
from __future__ import annotations


class NightShiftError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str = "", *, code: str | None = None, details=None):
        super().__init__(message or self.code)
        if code:
            self.code = code
        self.message = message or self.code
        self.details = details


class ValidationError(NightShiftError):
    code = "VALIDATION_ERROR"
    http_status = 400


class Unauthorized(NightShiftError):
    code = "UNAUTHORIZED"
    http_status = 401


class Forbidden(NightShiftError):
    code = "FORBIDDEN"
    http_status = 403


class NotFound(NightShiftError):
    code = "NOT_FOUND"
    http_status = 404


class Conflict(NightShiftError):
    code = "CONFLICT"
    http_status = 409


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"


class PayloadTooLarge(NightShiftError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413


class RateLimited(NightShiftError):
    code = "RATE_LIMITED"
    http_status = 429


class LeaseLost(Exception):
    """The worker no longer owns the job (lease expired and was reclaimed, or fence mismatch)."""


class TransientError(Exception):
    def __init__(self, code: str, message: str = "", retry_after: float | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.retry_after = retry_after


class PermanentError(Exception):
    category = "infrastructure"

    def __init__(self, code: str, message: str = "", extra: dict | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.extra = extra or {}


class GateBlocked(PermanentError):
    """A safety/verification gate refused to let the job succeed (not an infrastructure fault)."""

    category = "gate_blocked"


class WorkflowSignal(Exception):
    pass


class CancelRequested(WorkflowSignal):
    pass


class PauseRequested(WorkflowSignal):
    pass


class ReplanRequired(WorkflowSignal):
    """Preconditions changed. Checkpoints after ``after_stage`` are invalidated, the job re-enters
    ``target_state`` and any open approval is superseded (fresh approval is required)."""

    def __init__(self, after_stage: str | None, target_state: str, reason: str):
        super().__init__(reason)
        self.after_stage = after_stage
        self.target_state = target_state
        self.reason = reason


class DeadlineExceeded(WorkflowSignal):
    pass


class ApprovalExpired(WorkflowSignal):
    pass


class ApprovalRejected(WorkflowSignal):
    def __init__(self, outcome: str, reason: str):
        super().__init__(reason)
        self.outcome = outcome
        self.reason = reason


class SimulatedCrash(BaseException):
    """TEST ONLY: emulates the worker process dying abruptly."""
