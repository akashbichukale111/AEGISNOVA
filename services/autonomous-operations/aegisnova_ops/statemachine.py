"""Explicit legal-transition tables for workflow runs and notifications."""
from .contracts import RunStatus as R, NotifStatus as N


class IllegalTransition(Exception):
    pass


RUN_TRANSITIONS = {
    R.QUEUED: {R.RUNNING, R.CANCELLED, R.PAUSED, R.FAILED},
    R.RUNNING: {R.WAITING_FOR_APPROVAL, R.RETRY_WAIT, R.SUCCEEDED, R.FAILED, R.CANCELLED, R.QUEUED},
    R.WAITING_FOR_APPROVAL: {R.QUEUED, R.CANCELLED, R.FAILED},
    R.RETRY_WAIT: {R.RUNNING, R.FAILED, R.CANCELLED, R.PAUSED},
    R.PAUSED: {R.QUEUED, R.RETRY_WAIT, R.CANCELLED},
    R.FAILED: {R.DEAD_LETTERED, R.QUEUED},
    R.DEAD_LETTERED: {R.QUEUED},
    R.SUCCEEDED: set(),
    R.CANCELLED: set(),
}

NOTIF_TRANSITIONS = {
    N.CREATED: {N.QUEUED, N.SUPPRESSED, N.SENDING, N.FAILED},
    N.QUEUED: {N.SENDING, N.SUPPRESSED, N.FAILED},
    N.SENDING: {N.ACCEPTED, N.RETRYING, N.FAILED, N.UNKNOWN, N.DEAD_LETTERED, N.SUPPRESSED},
    N.RETRYING: {N.SENDING, N.SUPPRESSED, N.FAILED},
    N.ACCEPTED: {N.DELIVERED, N.FAILED},
    N.UNKNOWN: {N.ACCEPTED, N.DELIVERED, N.FAILED, N.QUEUED},
    N.DEAD_LETTERED: {N.QUEUED},
    N.DELIVERED: set(),
    N.FAILED: set(),
    N.SUPPRESSED: set(),
}


def check_run(frm, to):
    if to not in RUN_TRANSITIONS.get(frm, set()):
        raise IllegalTransition(f"run: {frm} -> {to} is not a legal transition")


def check_notif(frm, to):
    if to not in NOTIF_TRANSITIONS.get(frm, set()):
        raise IllegalTransition(f"notification: {frm} -> {to} is not a legal transition")
