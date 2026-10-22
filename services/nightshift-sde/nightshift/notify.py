"""Notification outbox. Notifications inform; they are never credentials and never carry secrets.

Channels
* ``local``   — records the notification in the outbox (status ``recorded_local``). This is NOT external delivery.
* ``webhook`` — optional HTTPS POST (NIGHTSHIFT_NOTIFY_WEBHOOK_URL), SSRF-guarded; status ``delivered``/``failed``.
Email / SMS / WhatsApp are NOT implemented in this standalone build (no provider credentials available).
Enqueue is idempotent per (job, event type) so replays cannot spam.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .errors import PermanentError, TransientError
from .providers import validate_https_url
from .redact import REDACTOR
from .retry import classify_exception
from .store import Store
from .util import iso, jdumps, new_id

MAX_DELIVERY_ATTEMPTS = 5


class Notifier:
    def __init__(self, store: Store, settings, transport=None):
        self.store = store
        self.settings = settings
        self._transport = transport or self._post

    def channels(self) -> list[str]:
        return ["local"] + (["webhook"] if self.settings.notify_webhook_url else [])

    def enqueue(self, job_id: str | None, event_type: str, payload: dict) -> None:
        now = iso(self.store.clock.now())
        safe = REDACTOR.obj(payload)
        with self.store.db.tx() as c:
            for ch in self.channels():
                key = f"{job_id or 'system'}:{event_type}:{ch}"
                c.execute(
                    "INSERT OR IGNORE INTO notifications(id, job_id, event_type, channel, idempotency_key, payload, status, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (new_id("ntf"), job_id, event_type, ch, key, jdumps(safe), "pending", now, now))

    def _post(self, url: str, body: bytes):
        validate_https_url(url)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "nightshift-sde/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status

    def dispatch_pending(self, limit: int = 20) -> int:
        n = 0
        rows = self.store.db.read().execute(
            "SELECT * FROM notifications WHERE status IN ('pending','failed') AND attempts<? ORDER BY created_at LIMIT ?",
            (MAX_DELIVERY_ATTEMPTS, limit)).fetchall()
        for r in rows:
            now = iso(self.store.clock.now())
            if r["channel"] == "local":
                status, err = "recorded_local", None
            else:
                try:
                    code = self._transport(self.settings.notify_webhook_url, r["payload"].encode())
                    status, err = ("delivered", None) if 200 <= int(code) < 300 else ("failed", f"HTTP {code}")
                except Exception as e:  # noqa: BLE001
                    _, c, _ = classify_exception(e)
                    status, err = "failed", c
            with self.store.db.tx() as c:
                c.execute("UPDATE notifications SET status=?, attempts=attempts+1, last_error=?, updated_at=? WHERE id=?",
                          (status, err, now, r["id"]))
            n += 1
        return n
