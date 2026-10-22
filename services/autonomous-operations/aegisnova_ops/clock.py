"""Injectable clock so tests are deterministic."""
from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%dT%H:%M:%S.%fZ"


def iso(dt):
    return dt.astimezone(timezone.utc).strftime(FMT)


def parse_iso(s):
    return datetime.strptime(s, FMT).replace(tzinfo=timezone.utc)


class Clock:
    def now(self):
        return datetime.now(timezone.utc)

    def now_iso(self):
        return iso(self.now())

    def plus_iso(self, seconds):
        return iso(self.now() + timedelta(seconds=seconds))


class FakeClock(Clock):
    def __init__(self, start="2026-01-01T00:00:00.000000Z"):
        self._now = parse_iso(start)

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now = self._now + timedelta(seconds=seconds)
