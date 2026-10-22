"""Measured metrics, deterministic alarm evaluation, local metric recording.
Unavailable metrics are reported as None (never fabricated zeros)."""
import os
from datetime import timedelta

from . import SCHEMA_VERSION
from .clock import iso, parse_iso
from .store import jdump
from .util import new_id

CHANNELS = ("local_sink", "email", "sms", "whatsapp")

# name, metric, comparison, default threshold, severity, runbook anchor, cooldown_s, description
ALARM_TABLE = [
    ("WorkflowFailures", "workflow_failed_recent", ">=", 3, "critical", "runbook-workflow-failures", 300, "Failed/dead-lettered runs in the last hour"),
    ("OldestRunAge", "oldest_active_run_age_s", ">", 1800, "warning", "runbook-stuck-runs", 300, "Oldest non-terminal, non-waiting run age (s)"),
    ("StuckRuns", "stuck_runs", ">=", 1, "warning", "runbook-stuck-runs", 300, "Runs RUNNING/QUEUED with no progress"),
    ("ApprovalWaitDuration", "approval_wait_max_s", ">", 3600, "info", "runbook-approvals", 600, "Longest pending approval wait (s)"),
    ("ExpiredApprovals", "approvals_expired_recent", ">=", 1, "warning", "runbook-approvals", 600, "Approvals expired in the last hour"),
    ("QueueDepth", "queue_depth", ">", 500, "warning", "runbook-queue-backlog", 300, "Visible queue messages"),
    ("QueueAge", "queue_oldest_age_s", ">", 900, "warning", "runbook-queue-backlog", 300, "Oldest pending queue message age (s)"),
    ("DeadLetterQueue", "dlq_open", ">=", 1, "critical", "runbook-dlq", 300, "Open dead-letter records"),
    ("WorkerHeartbeatStale", "worker_heartbeat_age_s", ">", 30, "critical", "runbook-worker-heartbeat", 60, "Seconds since last worker heartbeat"),
    ("NotificationFailureRateEmail", "notification_failure_rate:email", ">", 0.5, "warning", "runbook-notification-failures", 600, "Email failure ratio (1h)"),
    ("NotificationFailureRateSms", "notification_failure_rate:sms", ">", 0.5, "warning", "runbook-notification-failures", 600, "SMS failure ratio (1h)"),
    ("NotificationFailureRateWhatsApp", "notification_failure_rate:whatsapp", ">", 0.5, "warning", "runbook-notification-failures", 600, "WhatsApp failure ratio (1h)"),
    ("ProviderCircuitOpen", "provider_circuit_open", ">=", 1, "critical", "runbook-provider-circuit", 300, "Providers with an open circuit breaker"),
    ("RedriveLoop", "redrive_recent", ">=", 10, "warning", "runbook-redrive-loops", 600, "Redrives in the last hour"),
    ("OutboxBacklog", "outbox_backlog", ">", 100, "warning", "runbook-outbox", 300, "Notifications awaiting dispatch"),
    ("OutboxOldest", "outbox_oldest_age_s", ">", 600, "warning", "runbook-outbox", 300, "Oldest unsent notification age (s)"),
]
OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b}


def alarm_definitions(env=None):
    """Alarm thresholds are defaults, overridable via AEGIS_ALARM_<NAME>_THRESHOLD. They are NOT universal safety claims."""
    env = os.environ if env is None else env
    out = []
    for name, metric, op, thr, sev, rb, cd, desc in ALARM_TABLE:
        ov = env.get(f"AEGIS_ALARM_{name.upper()}_THRESHOLD")
        out.append({"name": name, "metric": metric, "comparison": op, "threshold": float(ov) if ov else float(thr),
                    "severity": sev, "runbook": f"docs/OBSERVABILITY_AND_RUNBOOKS.md#{rb}", "cooldown_s": cd, "description": desc})
    return out


class Observability:
    def __init__(self, engine, env=None, emitter=None):
        self.e, self.s, self.clock, self.cfg = engine, engine.s, engine.clock, engine.cfg
        self.defs = alarm_definitions(env)
        self.emitter = emitter   # CloudWatchEmitter or None (local mode emits nothing to CloudWatch)

    def _age(self, ts):
        return (self.clock.now() - parse_iso(ts)).total_seconds() if ts else None

    def snapshot(self):
        s, now = self.s, self.clock.now()
        hour = iso(now - timedelta(hours=1))
        m = {}
        qs = self.e.queue_stats()
        m["queue_depth"], m["queue_oldest_age_s"], m["dlq_open"] = qs["depth"], qs["oldest_pending_age_s"], qs["dlq_open"]
        hb = s.one("SELECT MAX(last_beat_at) m FROM heartbeats")["m"]
        m["worker_heartbeat_age_s"] = self._age(hb)
        m["workflow_failed_recent"] = s.one("SELECT COUNT(*) c FROM workflow_runs WHERE status IN ('FAILED','DEAD_LETTERED') AND updated_at>=?", (hour,))["c"]
        old = s.one("SELECT MIN(updated_at) m FROM workflow_runs WHERE status IN ('QUEUED','RUNNING','RETRY_WAIT')")["m"]
        m["oldest_active_run_age_s"] = self._age(old)
        m["stuck_runs"] = len(self.e.stuck_runs())
        pend = s.one("SELECT MIN(created_at) m FROM approvals WHERE status='PENDING'")["m"]
        m["approval_wait_max_s"] = self._age(pend)
        m["approvals_expired_recent"] = s.one("SELECT COUNT(*) c FROM approvals WHERE status='EXPIRED' AND updated_at>=?", (hour,))["c"]
        for ch in CHANNELS:
            r = s.one("SELECT SUM(status IN ('FAILED','DEAD_LETTERED')) f, COUNT(*) t FROM notifications WHERE channel=? AND mode!='LOCAL' AND status IN ('ACCEPTED','DELIVERED','FAILED','DEAD_LETTERED','UNKNOWN') AND updated_at>=?", (ch, hour))
            m[f"notification_failure_rate:{ch}"] = (r["f"] or 0) / r["t"] if r["t"] else None
        m["provider_circuit_open"] = s.one("SELECT COUNT(*) c FROM provider_health WHERE state='OPEN'")["c"]
        m["redrive_recent"] = s.one("SELECT COUNT(*) c FROM events WHERE type='queue.redriven' AND ts>=?", (hour,))["c"]
        m["outbox_backlog"] = s.one("SELECT COUNT(*) c FROM notifications WHERE status IN ('CREATED','QUEUED','RETRYING')")["c"]
        ob = s.one("SELECT MIN(created_at) m FROM notifications WHERE status IN ('CREATED','QUEUED','RETRYING')")["m"]
        m["outbox_oldest_age_s"] = self._age(ob)
        m["recovery_actions_recent"] = s.one("SELECT COUNT(*) c FROM events WHERE actor='recovery' AND ts>=?", (hour,))["c"]
        m["notification_retrying"] = s.one("SELECT COUNT(*) c FROM notifications WHERE status='RETRYING'")["c"]
        return m

    def record_local(self, snap):
        with self.s.tx():
            for k, v in snap.items():
                if v is not None:
                    self.s.x("INSERT INTO metrics(name,value,labels_json,ts,source) VALUES(?,?,?,?,?)", (k, float(v), None, iso(self.clock.now()), "local"))

    def evaluate(self):
        snap = self.snapshot()
        self.record_local(snap)
        if self.emitter:
            self.emitter.emit({k: v for k, v in snap.items() if v is not None})
        events = []
        now = iso(self.clock.now())
        with self.s.tx():
            for d in self.defs:
                v = snap.get(d["metric"])
                st = self.s.one("SELECT * FROM alarm_state WHERE alarm_name=?", (d["name"],))
                if v is None:
                    self._set_state(d["name"], "UNAVAILABLE", None, st)
                    continue
                breach = OPS[d["comparison"]](v, d["threshold"])
                if breach and (not st or st["state"] != "ALARM"):
                    if st and st["cooldown_until"] and st["cooldown_until"] > now:
                        self.s.x("UPDATE alarm_state SET suppressed_count=suppressed_count+1 WHERE alarm_name=?", (d["name"],))
                        continue
                    eid = new_id("alm")
                    expl = f"{d['metric']} = {round(v, 3)} breached threshold {d['comparison']} {d['threshold']} ({d['description']})"
                    self.s.x("INSERT INTO alarm_events(id,schema_version,alarm_name,severity,state,metric,value,threshold,triggered_at,runbook,explanation) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (eid, SCHEMA_VERSION, d["name"], d["severity"], "ALARM", d["metric"], float(v), d["threshold"], now, d["runbook"], expl))
                    self.s.x("INSERT INTO alarm_state(alarm_name,state,last_value,since,active_event_id) VALUES(?,?,?,?,?) ON CONFLICT(alarm_name) DO UPDATE SET state='ALARM', last_value=excluded.last_value, since=excluded.since, active_event_id=excluded.active_event_id",
                             (d["name"], "ALARM", float(v), now, eid))
                    self.e._event("alarm", eid, "operations.alarm_triggered", detail={"alarm": d["name"], "value": v})
                    events.append(("triggered", d["name"]))
                elif breach:
                    self.s.x("UPDATE alarm_state SET last_value=? WHERE alarm_name=?", (float(v), d["name"]))
                elif st and st["state"] == "ALARM":
                    ev = self.s.one("SELECT * FROM alarm_events WHERE id=?", (st["active_event_id"],))
                    expl = (ev["explanation"] or "") + f" | resolved: {d['metric']} = {round(v, 3)} no longer breaches {d['comparison']} {d['threshold']}"
                    self.s.x("UPDATE alarm_events SET state='RESOLVED', resolved_at=?, explanation=? WHERE id=?", (now, expl, ev["id"]))
                    self.s.x("UPDATE alarm_state SET state='OK', last_value=?, since=?, cooldown_until=?, active_event_id=NULL WHERE alarm_name=?",
                             (float(v), now, iso(self.clock.now() + timedelta(seconds=d["cooldown_s"])), d["name"]))
                    self.e._event("alarm", ev["id"], "operations.alarm_resolved", detail={"alarm": d["name"], "value": v})
                    events.append(("resolved", d["name"]))
                else:
                    self._set_state(d["name"], "OK", v, st)
        return {"events": events, "snapshot": snap}

    def _set_state(self, name, state, value, st):
        now = iso(self.clock.now())
        if not st:
            self.s.x("INSERT INTO alarm_state(alarm_name,state,last_value,since) VALUES(?,?,?,?)", (name, state, value, now))
        elif st["state"] != state and st["state"] != "ALARM":
            self.s.x("UPDATE alarm_state SET state=?, last_value=?, since=? WHERE alarm_name=?", (state, value, now, name))
        elif st["state"] == "ALARM" and state == "UNAVAILABLE":
            pass  # keep ALARM until a measured value resolves it

    def alarm_states(self):
        rows = {r["alarm_name"]: r for r in self.s.q("SELECT * FROM alarm_state")}
        out = []
        for d in self.defs:
            r = rows.get(d["name"])
            out.append({**d, "state": r["state"] if r else "UNAVAILABLE", "last_value": r["last_value"] if r else None,
                        "since": r["since"] if r else None, "suppressed_count": r["suppressed_count"] if r else 0})
        return out

    def alarm_events(self, limit=100):
        return self.s.q("SELECT * FROM alarm_events ORDER BY triggered_at DESC LIMIT ?", (limit,))

    def overview(self, env_label):
        s = self.s
        runs = {r["status"]: r["c"] for r in s.q("SELECT status, COUNT(*) c FROM workflow_runs GROUP BY status")}
        by_state = {"queued": runs.get("QUEUED", 0), "running": runs.get("RUNNING", 0),
                    "waiting_for_approval": runs.get("WAITING_FOR_APPROVAL", 0),
                    "retrying": runs.get("RETRY_WAIT", 0), "succeeded": runs.get("SUCCEEDED", 0),
                    "failed": runs.get("FAILED", 0) + runs.get("DEAD_LETTERED", 0), "cancelled": runs.get("CANCELLED", 0),
                    "paused": runs.get("PAUSED", 0)}
        notif = {}
        for r in s.q("SELECT channel, status, COUNT(*) c FROM notifications GROUP BY channel, status"):
            notif.setdefault(r["channel"], {})[r["status"]] = r["c"]
        hb = s.one("SELECT MAX(last_beat_at) m FROM heartbeats")["m"]
        qs = self.e.queue_stats()
        return {"environment": env_label, "runs_by_state": by_state, "notifications_by_channel": notif, "queue": qs,
                "worker_heartbeat": {"last_beat_at": hb, "age_s": self._age(hb)},
                "providers": s.q("SELECT * FROM provider_health"), "generated_at": iso(self.clock.now())}
