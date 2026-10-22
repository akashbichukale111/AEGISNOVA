"""Small shared helpers: clocks, ids, canonical JSON, hashing."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
ISO_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


class Clock:
    """Wall clock. Tests inject FakeClock so time-dependent behaviour is deterministic."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock(Clock):
    """Deterministic clock for tests (TEST DATA ONLY)."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 10, 20, 5, 0, 0, tzinfo=UTC)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float = 0, **kwargs) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(seconds=seconds, **kwargs)
            return self._now

    def set(self, dt: datetime) -> None:
        with self._lock:
            self._now = dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    """Fixed-width UTC ISO string; lexicographic order == chronological order."""
    return dt.astimezone(UTC).strftime(ISO_FMT)


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FMT).replace(tzinfo=UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


_CORR_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def valid_correlation_id(value: str | None) -> bool:
    return bool(value) and bool(_CORR_RE.match(value))


def new_correlation_id() -> str:
    return "corr_" + uuid.uuid4().hex[:20]


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def jloads(value, default=None):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def jdumps(obj) -> str:
    return canonical_json(obj)
