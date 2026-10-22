"""Durable SQLite store (stdlib only). The `events` table is append-only (enforced by triggers)."""
import json
import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_runs(
 id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, workflow_type TEXT NOT NULL, status TEXT NOT NULL,
 step TEXT NOT NULL, correlation_id TEXT NOT NULL, causation_id TEXT, idempotency_key TEXT NOT NULL UNIQUE,
 tenant TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, requires_approval INTEGER NOT NULL,
 approval_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, attempt_base INTEGER NOT NULL DEFAULT 0,
 retry_started_at TEXT, next_retry_at TEXT, paused_from TEXT, failure_class TEXT, last_error TEXT, cancel_reason TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS ix_runs_status ON workflow_runs(status);
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, schema_version TEXT, entity_type TEXT NOT NULL,
 entity_id TEXT NOT NULL, run_id TEXT, type TEXT NOT NULL, from_state TEXT, to_state TEXT, step TEXT,
 detail_json TEXT, correlation_id TEXT, causation_id TEXT, actor TEXT NOT NULL, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'events is append-only'); END;
CREATE TABLE IF NOT EXISTS workflow_attempts(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step TEXT NOT NULL, attempt_no INTEGER NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, outcome TEXT, error_class TEXT, error TEXT, correlation_id TEXT);
CREATE TABLE IF NOT EXISTS side_effects(key TEXT PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL, marker TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals(
 id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, run_id TEXT NOT NULL, action TEXT NOT NULL, scope TEXT NOT NULL,
 risk_level TEXT NOT NULL, action_hash TEXT NOT NULL, requester TEXT, reason TEXT, expires_at TEXT NOT NULL,
 status TEXT NOT NULL, provider TEXT, provider_ref TEXT, blocked_reason TEXT, decision_ref TEXT, dev_only INTEGER,
 decided_at TEXT, correlation_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, nonce TEXT);
CREATE TABLE IF NOT EXISTS decision_nonces(event_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS callback_tokens(approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, token TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE IF NOT EXISTS queue_messages(
 id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, queue TEXT NOT NULL, run_id TEXT, kind TEXT, dedupe_key TEXT NOT NULL UNIQUE,
 event_id TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,
 receive_count INTEGER NOT NULL DEFAULT 0, receive_base INTEGER NOT NULL DEFAULT 0, redrive_count INTEGER NOT NULL DEFAULT 0,
 visible_at TEXT NOT NULL, leased_until TEXT, enqueued_at TEXT NOT NULL, updated_at TEXT NOT NULL, correlation_id TEXT);
CREATE TABLE IF NOT EXISTS dead_letters(
 id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL, queue_message_id TEXT,
 event_id TEXT, payload_hash TEXT NOT NULL, payload_ref TEXT, error_class TEXT NOT NULL, error TEXT,
 attempt_history_json TEXT, status TEXT NOT NULL, redrive_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 redriven_at TEXT, correlation_id TEXT);
CREATE TABLE IF NOT EXISTS notifications(
 id TEXT PRIMARY KEY, schema_version TEXT NOT NULL, run_id TEXT, correlation_id TEXT NOT NULL, channel TEXT NOT NULL,
 mode TEXT NOT NULL, destination TEXT, destination_hash TEXT NOT NULL, destination_masked TEXT, template TEXT NOT NULL,
 params_json TEXT, status TEXT NOT NULL, provider TEXT, provider_message_id TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 attempt_base INTEGER NOT NULL DEFAULT 0, first_attempt_at TEXT, next_attempt_at TEXT, last_error TEXT, error_class TEXT,
 suppress_reason TEXT, receipt_state TEXT, delivery_verified INTEGER NOT NULL DEFAULT 0, confirmed_real INTEGER NOT NULL DEFAULT 0,
 idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_notif_status ON notifications(status);
CREATE INDEX IF NOT EXISTS ix_notif_pmid ON notifications(provider_message_id);
CREATE TABLE IF NOT EXISTS notification_attempts(
 id TEXT PRIMARY KEY, schema_version TEXT, notification_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, outcome TEXT NOT NULL, provider TEXT NOT NULL, provider_message_id TEXT, error_class TEXT, error TEXT, correlation_id TEXT);
CREATE TABLE IF NOT EXISTS delivery_receipts(
 id TEXT PRIMARY KEY, schema_version TEXT, notification_id TEXT, provider TEXT NOT NULL, provider_event_id TEXT NOT NULL,
 provider_message_id TEXT, status TEXT NOT NULL, provider_ts TEXT, received_at TEXT NOT NULL, verified INTEGER NOT NULL,
 source TEXT NOT NULL, applied INTEGER NOT NULL DEFAULT 0, note TEXT, UNIQUE(provider, provider_event_id));
CREATE TABLE IF NOT EXISTS consents(destination_hash TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(destination_hash, channel));
CREATE TABLE IF NOT EXISTS provider_health(
 provider TEXT PRIMARY KEY, state TEXT NOT NULL, consecutive_failures INTEGER NOT NULL DEFAULT 0, opened_at TEXT,
 cooldown_until TEXT, last_success_at TEXT, last_failure_at TEXT, last_error TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, value REAL NOT NULL, labels_json TEXT, ts TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alarm_state(alarm_name TEXT PRIMARY KEY, state TEXT NOT NULL, last_value REAL, since TEXT NOT NULL, cooldown_until TEXT, active_event_id TEXT, suppressed_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alarm_events(
 id TEXT PRIMARY KEY, schema_version TEXT, alarm_name TEXT NOT NULL, severity TEXT NOT NULL, state TEXT NOT NULL, metric TEXT NOT NULL,
 value REAL, threshold REAL NOT NULL, triggered_at TEXT NOT NULL, resolved_at TEXT, runbook TEXT NOT NULL, explanation TEXT);
CREATE TABLE IF NOT EXISTS heartbeats(worker_id TEXT PRIMARY KEY, last_beat_at TEXT NOT NULL, info_json TEXT);
"""


class Store:
    def __init__(self, path, clock):
        self.path = path
        self.clock = clock
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.RLock()
        self._depth = 0
        self.conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self.lock:
            if self._depth == 0:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.execute("COMMIT")

    def q(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def x(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params)

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def jdump(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"))


def jload(s, default=None):
    if s is None:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default
