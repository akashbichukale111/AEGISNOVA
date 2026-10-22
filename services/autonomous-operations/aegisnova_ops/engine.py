"""Deterministic workflow engine over the durable store.

Flow: START -> VALIDATE -> (WAITING_FOR_APPROVAL) -> EXECUTE_SAFE_ACTION -> NOTIFY -> COMPLETE.
Notification intent is written in the SAME transaction as the NOTIFY->COMPLETE transition (outbox)."""
import random
import threading
from datetime import timedelta

from . import SCHEMA_VERSION
from . import contracts as C
from .contracts import RunStatus as R, Step, NotifStatus as N, ValidationError
from .clock import iso, parse_iso
from .governance import DecisionRejected, compute_action_hash
from .statemachine import check_run, check_notif, IllegalTransition
from .store import jdump, jload
from .util import new_id, sha256_hex, redact, mask_destination


class QueueFull(Exception):
    pass


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class Refused(Exception):
    """Operation refused by a safety rule (limits, loop guard, wrong state)."""


class StepError(Exception):
    def __init__(self, error_class, message, transient):
        super().__init__(message)
        self.error_class, self.transient = error_class, transient


class Backoff:
    """Exponential backoff with optional jitter; deterministic when jitter=0 or seeded rng."""
    def __init__(self, base=2.0, factor=2.0, cap=300.0, jitter=0.2, rng=None):
        self.base, self.factor, self.cap, self.jitter = base, factor, cap, jitter
        self.rng = rng or random.Random()

    def delay(self, attempt):
        d = min(self.cap, self.base * (self.factor ** max(0, attempt - 1)))
        if self.jitter:
            d *= 1 + self.rng.uniform(-self.jitter, self.jitter)
        return max(0.0, d)


class Engine:
    def __init__(self, store, clock, config, governance, providers, backoff=None, metrics_sink=None, worker_id="worker-1"):
        self.s, self.clock, self.cfg, self.gov = store, clock, config, governance
        self.providers = providers            # list of Provider objects; resolved by (channel, mode)
        self.backoff = backoff or Backoff()
        self.worker_id = worker_id
        self.metrics_sink = metrics_sink
        self._stop = threading.Event()

    # ------------------------------------------------------------------ helpers
    def _now(self):
        return self.clock.now_iso()

    def _event(self, entity_type, entity_id, type_, run_id=None, frm=None, to=None, step=None, detail=None,
               corr=None, caus=None, actor="system"):
        self.s.x("INSERT INTO events(id,schema_version,entity_type,entity_id,run_id,type,from_state,to_state,step,detail_json,"
                 "correlation_id,causation_id,actor,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (new_id("ev"), SCHEMA_VERSION, entity_type, entity_id, run_id, type_, frm, to, step,
                  jdump(detail) if detail else None, corr, caus, actor, self._now()))

    def audit(self, actor, action, entity_type, entity_id, detail=None, run_id=None):
        self._event(entity_type, entity_id, "audit." + action, run_id=run_id, detail=detail, actor=actor)

    def get_run(self, run_id):
        r = self.s.one("SELECT * FROM workflow_runs WHERE id=?", (run_id,))
        if not r:
            raise NotFound(f"run {run_id}")
        return r

    def _transition(self, run_id, to, step=None, actor="system", detail=None, **fields):
        with self.s.tx():
            r = self.get_run(run_id)
            check_run(r["status"], to)
            now = self._now()
            sets, vals = ["status=?", "updated_at=?"], [to, now]
            if step:
                sets.append("step=?"); vals.append(step)
            if to in R.TERMINAL and to != R.FAILED:
                sets.append("finished_at=?"); vals.append(now)
            for k, v in fields.items():
                assert k in ("approval_id", "attempts", "attempt_base", "retry_started_at", "next_retry_at", "paused_from",
                             "failure_class", "last_error", "cancel_reason", "started_at")
                sets.append(f"{k}=?"); vals.append(v)
            self.s.x(f"UPDATE workflow_runs SET {', '.join(sets)} WHERE id=?", (*vals, run_id))
            self._event("run", run_id, "run.transition", run_id=run_id, frm=r["status"], to=to, step=step or r["step"],
                        detail=detail, corr=r["correlation_id"], actor=actor)

    def _set_step(self, run_id, step, actor="system"):
        with self.s.tx():
            r = self.get_run(run_id)
            self.s.x("UPDATE workflow_runs SET step=?, updated_at=? WHERE id=?", (step, self._now(), run_id))
            self._event("run", run_id, "step.completed", run_id=run_id, step=r["step"], to=step,
                        corr=r["correlation_id"], actor=actor)

    def _record_metric(self, name, value, labels=None):
        self.s.x("INSERT INTO metrics(name,value,labels_json,ts,source) VALUES(?,?,?,?,?)",
                 (name, float(value), jdump(labels) if labels else None, self._now(), "local"))

    # ------------------------------------------------------------------ queue
    def _enqueue(self, run_id, kind, dedupe_key, corr, visible_at=None):
        with self.s.tx():
            existing = self.s.one("SELECT * FROM queue_messages WHERE dedupe_key=?", (dedupe_key,))
            if existing:
                self._event("queue", existing["id"], "queue.duplicate_ignored", run_id=run_id, corr=corr,
                            detail={"dedupe_key": dedupe_key})
                return existing, False
            depth = self.s.one("SELECT COUNT(*) c FROM queue_messages WHERE status IN ('VISIBLE','IN_FLIGHT')")["c"]
            if depth >= self.cfg.queue_max_depth:
                raise QueueFull(f"queue depth {depth} at bound {self.cfg.queue_max_depth}")
            body = {"run_id": run_id, "kind": kind, "schema_version": SCHEMA_VERSION}
            C.validate("QueueMessage", body)
            now = self._now()
            mid = new_id("msg")
            self.s.x("INSERT INTO queue_messages(id,schema_version,queue,run_id,kind,dedupe_key,event_id,payload_json,payload_hash,"
                     "status,visible_at,enqueued_at,updated_at,correlation_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (mid, SCHEMA_VERSION, "work", run_id, kind, dedupe_key, new_id("qe"), jdump(body), sha256_hex(jdump(body)),
                      "VISIBLE", visible_at or now, now, now, corr))
            self._event("queue", mid, "queue.enqueued", run_id=run_id, corr=corr, detail={"kind": kind})
            return self.s.one("SELECT * FROM queue_messages WHERE id=?", (mid,)), True

    def inject_raw_message(self, run_id, raw_payload_json, actor="test"):
        """Test/dev helper: put an arbitrary (possibly malformed) payload on the queue; validated at claim time."""
        now = self._now()
        mid = new_id("msg")
        self.s.x("INSERT INTO queue_messages(id,schema_version,queue,run_id,kind,dedupe_key,event_id,payload_json,payload_hash,"
                 "status,visible_at,enqueued_at,updated_at,correlation_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (mid, SCHEMA_VERSION, "work", run_id, None, "raw:" + mid, new_id("qe"), raw_payload_json,
                  sha256_hex(raw_payload_json), "VISIBLE", now, now, now, None))
        return mid

    def queue_stats(self):
        now = self._now()
        depth = self.s.one("SELECT COUNT(*) c FROM queue_messages WHERE status='VISIBLE'")["c"]
        inflight = self.s.one("SELECT COUNT(*) c FROM queue_messages WHERE status='IN_FLIGHT'")["c"]
        dlq = self.s.one("SELECT COUNT(*) c FROM dead_letters WHERE status='OPEN'")["c"]
        oldest = self.s.one("SELECT MIN(enqueued_at) m FROM queue_messages WHERE status IN ('VISIBLE','IN_FLIGHT')")["m"]
        retries = self.s.one("SELECT COUNT(*) c FROM workflow_attempts WHERE outcome='RETRY'")["c"]
        return {"depth": depth, "in_flight": inflight, "dlq_open": dlq, "retry_attempts": retries,
                "oldest_pending_age_s": (parse_iso(now) - parse_iso(oldest)).total_seconds() if oldest else None,
                "max_depth": self.cfg.queue_max_depth}

    # ------------------------------------------------------------------ run lifecycle
    def start_run(self, req, actor="operator"):
        data = C.validate("WorkflowStartRequest", req)
        if data["workflow_type"] not in C.WORKFLOW_DEFINITIONS:
            raise ValidationError("unknown workflow_type")
        payload = C.validate_sample_payload(data["payload"])
        phash = sha256_hex(jdump(payload))
        idem = data.get("idempotency_key") or new_id("idem")
        with self.s.tx():
            ex = self.s.one("SELECT * FROM workflow_runs WHERE idempotency_key=?", (idem,))
            if ex:
                if ex["payload_hash"] != phash:
                    raise Conflict("idempotency key reused with a different payload")
                self._event("run", ex["id"], "run.duplicate_start_ignored", run_id=ex["id"], corr=ex["correlation_id"], actor=actor)
                return ex, False
            rid, now = new_id("run"), self._now()
            corr = data.get("correlation_id") or new_id("corr")
            self.s.x("INSERT INTO workflow_runs(id,schema_version,workflow_type,status,step,correlation_id,causation_id,idempotency_key,"
                     "tenant,payload_json,payload_hash,requires_approval,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (rid, SCHEMA_VERSION, data["workflow_type"], R.QUEUED, Step.START, corr, data.get("causation_id"), idem,
                      data.get("tenant", "default"), jdump(payload), phash, int(payload["approval_required"]), now, now))
            self._event("run", rid, "run.created", run_id=rid, to=R.QUEUED, step=Step.START, corr=corr, actor=actor)
            self._enqueue(rid, "step", f"run:{rid}:start", corr)
        return self.get_run(rid), True

    def cancel_run(self, run_id, actor, reason="operator_cancel"):
        with self.s.tx():
            r = self.get_run(run_id)
            self._transition(run_id, R.CANCELLED, actor=actor, cancel_reason=reason, detail={"reason": reason})
            self.s.x("UPDATE queue_messages SET status='DONE', updated_at=? WHERE run_id=? AND status IN ('VISIBLE','IN_FLIGHT')",
                     (self._now(), run_id))
            if r["approval_id"]:
                self.s.x("UPDATE approvals SET status='REVOKED', updated_at=?, blocked_reason='run_cancelled' WHERE id=? AND status='PENDING'",
                         (self._now(), r["approval_id"]))
            self.audit(actor, "run.cancel", "run", run_id, {"reason": reason}, run_id)
        return self.get_run(run_id)

    def pause_run(self, run_id, actor):
        with self.s.tx():
            r = self.get_run(run_id)
            if r["status"] not in (R.QUEUED, R.RETRY_WAIT):
                raise Refused(f"pause is supported only for QUEUED or RETRY_WAIT runs (was {r['status']})")
            self._transition(run_id, R.PAUSED, actor=actor, paused_from=r["status"])
            self.audit(actor, "run.pause", "run", run_id, run_id=run_id)
        return self.get_run(run_id)

    def resume_paused(self, run_id, actor):
        with self.s.tx():
            r = self.get_run(run_id)
            if r["status"] != R.PAUSED:
                raise Refused("run is not PAUSED")
            self._transition(run_id, r["paused_from"] or R.QUEUED, actor=actor, paused_from=None)
            self.audit(actor, "run.resume", "run", run_id, run_id=run_id)
        return self.get_run(run_id)

    def retry_run(self, run_id, actor):
        """Manual retry of FAILED work. Only for retryable failure classes; never bypasses governance."""
        with self.s.tx():
            r = self.get_run(run_id)
            if r["status"] == R.DEAD_LETTERED:
                raise Refused("dead-lettered runs are recovered via DLQ redrive (admin, confirmed)")
            if r["status"] != R.FAILED:
                raise Refused(f"only FAILED runs can be retried (was {r['status']})")
            if r["failure_class"] not in ("transient", "timeout", "transient_exhausted"):
                raise Refused(f"failure class '{r['failure_class']}' is not safely retryable")
            self._transition(run_id, R.QUEUED, actor=actor, attempt_base=r["attempts"], retry_started_at=None,
                             failure_class=None, last_error=None)
            self._enqueue(run_id, "step", f"run:{run_id}:manual:{r['attempts']}", r["correlation_id"])
            self.audit(actor, "run.retry", "run", run_id, run_id=run_id)
        return self.get_run(run_id)

    def list_runs(self, q=None, status=None, workflow_type=None, since=None, correlation_id=None, limit=200):
        sql, p = "SELECT * FROM workflow_runs WHERE 1=1", []
        if status:
            sql += " AND status=?"; p.append(status)
        if workflow_type:
            sql += " AND workflow_type=?"; p.append(workflow_type)
        if since:
            sql += " AND created_at>=?"; p.append(since)
        if correlation_id:
            sql += " AND correlation_id=?"; p.append(correlation_id)
        if q:
            sql += " AND (id LIKE ? OR correlation_id LIKE ? OR idempotency_key LIKE ?)"; p += [f"%{q}%"] * 3
        sql += " ORDER BY created_at DESC LIMIT ?"
        p.append(min(int(limit), 500))
        return self.s.q(sql, p)

    def timeline(self, run_id):
        return self.s.q("SELECT * FROM events WHERE run_id=? OR (entity_type='run' AND entity_id=?) ORDER BY seq", (run_id, run_id))

    # ------------------------------------------------------------------ worker tick
    def heartbeat(self):
        self.s.x("INSERT INTO heartbeats(worker_id,last_beat_at,info_json) VALUES(?,?,?) ON CONFLICT(worker_id) DO UPDATE SET last_beat_at=excluded.last_beat_at",
                 (self.worker_id, self._now(), None))

    def tick(self, limit=None):
        """One worker iteration: heartbeat, sweep, process queue, deliver notifications. Bounded by cfg.concurrency."""
        self.heartbeat()
        self.sweep()
        n = 0
        for msg in self._claim(limit or self.cfg.concurrency):
            self._process(msg)
            n += 1
        sent = self.deliver_notifications()
        return {"processed": n, "notifications_attempted": sent}

    def drain(self, max_ticks=50):
        total = 0
        for _ in range(max_ticks):
            r = self.tick()
            total += r["processed"] + r["notifications_attempted"]
            if not r["processed"] and not r["notifications_attempted"]:
                break
        return total

    def run_forever(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # keep the worker alive; error is redacted and recorded
                self._event("worker", self.worker_id, "worker.error", detail={"error": redact(repr(e))})
            self._stop.wait(self.cfg.worker_interval_s)

    def stop(self):
        self._stop.set()

    def _claim(self, limit):
        now = self._now()
        claimed = []
        with self.s.tx():
            for m in self.s.q("SELECT id,run_id FROM queue_messages WHERE status='IN_FLIGHT' AND leased_until<=?", (now,)):
                self.s.x("UPDATE queue_messages SET status='VISIBLE', leased_until=NULL, updated_at=? WHERE id=?", (now, m["id"]))
                self._event("queue", m["id"], "queue.lease_expired", run_id=m["run_id"])
            rows = self.s.q(
                "SELECT m.* FROM queue_messages m LEFT JOIN workflow_runs r ON r.id=m.run_id "
                "WHERE m.status='VISIBLE' AND m.visible_at<=? AND (r.id IS NULL OR r.status IN ('QUEUED','RETRY_WAIT','RUNNING')) "
                "ORDER BY m.visible_at, m.enqueued_at LIMIT ?", (now, limit))
            for m in rows:
                rc = m["receive_count"] + 1
                if rc - m["receive_base"] > self.cfg.max_receive_count:
                    self.s.x("UPDATE queue_messages SET receive_count=? WHERE id=?", (rc, m["id"]))
                    run = self.s.one("SELECT * FROM workflow_runs WHERE id=?", (m["run_id"],)) if m["run_id"] else None
                    self._dead_letter(self.s.one("SELECT * FROM queue_messages WHERE id=?", (m["id"],)), run,
                                      "max_receive_exceeded", "message received more than the maximum allowed times")
                    continue
                self.s.x("UPDATE queue_messages SET status='IN_FLIGHT', receive_count=?, leased_until=?, updated_at=? WHERE id=?",
                         (rc, iso(self.clock.now() + timedelta(seconds=self.cfg.lease_s)), now, m["id"]))
                claimed.append(self.s.one("SELECT * FROM queue_messages WHERE id=?", (m["id"],)))
        return claimed

    def _ack(self, mid):
        self.s.x("UPDATE queue_messages SET status='DONE', leased_until=NULL, updated_at=? WHERE id=?", (self._now(), mid))

    def _release(self, mid, visible_at):
        self.s.x("UPDATE queue_messages SET status='VISIBLE', leased_until=NULL, visible_at=?, receive_base=receive_count, updated_at=? WHERE id=?",
                 (visible_at, self._now(), mid))

    def _dead_letter(self, msg, run, error_class, error):
        with self.s.tx():
            now = self._now()
            hist = []
            if run:
                hist = [{"step": a["step"], "attempt_no": a["attempt_no"], "outcome": a["outcome"], "error_class": a["error_class"],
                         "started_at": a["started_at"]} for a in self.s.q("SELECT * FROM workflow_attempts WHERE run_id=? ORDER BY attempt_no", (run["id"],))]
            self.s.x("UPDATE queue_messages SET status='DEAD', leased_until=NULL, updated_at=? WHERE id=?", (now, msg["id"]))
            did = new_id("dlq")
            self.s.x("INSERT INTO dead_letters(id,schema_version,kind,entity_id,queue_message_id,event_id,payload_hash,payload_ref,error_class,error,"
                     "attempt_history_json,status,created_at,correlation_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (did, SCHEMA_VERSION, "workflow" if run else "queue_message", run["id"] if run else msg["id"], msg["id"],
                      msg["event_id"], msg["payload_hash"], f"queue_messages/{msg['id']}", error_class, redact(error),
                      jdump(hist), "OPEN", now, run["correlation_id"] if run else None))
            self._event("queue", msg["id"], "queue.dead_lettered", run_id=run["id"] if run else None,
                        detail={"dlq_id": did, "error_class": error_class}, corr=run["correlation_id"] if run else None)
            if run and run["status"] not in R.TERMINAL:
                self._transition(run["id"], R.FAILED, failure_class=error_class, last_error=redact(error))
                self._transition(run["id"], R.DEAD_LETTERED, detail={"dlq_id": did})
        return did

    # ------------------------------------------------------------------ message processing
    def _process(self, msg):
        try:
            body = jload(msg["payload_json"])
            try:
                C.validate("QueueMessage", body)
            except (ValidationError, TypeError) as e:
                run = self.s.one("SELECT * FROM workflow_runs WHERE id=?", (msg["run_id"],)) if msg["run_id"] else None
                self._dead_letter(msg, run, "poison", f"malformed queue message: {e}")
                return
            run = self.s.one("SELECT * FROM workflow_runs WHERE id=?", (body["run_id"],))
            if not run:
                self._dead_letter(msg, None, "poison", "message references unknown run")
                return
            if run["status"] in R.TERMINAL or run["status"] in (R.WAITING_FOR_APPROVAL, R.PAUSED):
                with self.s.tx():
                    self._ack(msg["id"])
                    self._event("queue", msg["id"], "queue.skipped", run_id=run["id"], detail={"run_status": run["status"]})
                return
            if run["status"] in (R.QUEUED, R.RETRY_WAIT):
                self._transition(run["id"], R.RUNNING, started_at=run["started_at"] or self._now())
            self._advance(run["id"], msg)
        except Exception as e:
            self._event("queue", msg["id"], "queue.handler_error", run_id=msg["run_id"], detail={"error": redact(repr(e))})
            with self.s.lock:
                cur = self.s.one("SELECT status FROM queue_messages WHERE id=?", (msg["id"],))
                if cur and cur["status"] == "IN_FLIGHT":
                    self.s.x("UPDATE queue_messages SET leased_until=? WHERE id=?", (iso(self.clock.now() + timedelta(seconds=5)), msg["id"]))

    def _advance(self, run_id, msg):
        for _ in range(10):
            run = self.get_run(run_id)
            step = run["step"]
            if step == Step.START:
                self._set_step(run_id, Step.VALIDATE)
            elif step == Step.VALIDATE:
                if self._do_validate(run, msg) == "waiting":
                    return
            elif step == Step.EXECUTE:
                if not self._do_execute(run, msg):
                    return
            elif step == Step.NOTIFY:
                self._do_notify(run, msg)
                return
            else:
                with self.s.tx():
                    self._ack(msg["id"])
                return

    def _payload(self, run):
        return jload(run["payload_json"], {})

    def _do_validate(self, run, msg):
        payload = self._payload(run)
        try:
            C.validate_sample_payload(payload)
        except ValidationError as e:
            self._fail_permanent(run, msg, "validation", str(e))
            return "waiting"
        if not run["requires_approval"]:
            self._set_step(run["id"], Step.EXECUTE)
            return "continue"
        if run["approval_id"]:
            ap = self.s.one("SELECT * FROM approvals WHERE id=?", (run["approval_id"],))
            if ap and ap["status"] == "GRANTED":
                self._set_step(run["id"], Step.EXECUTE)
                return "continue"
            with self.s.tx():
                self._transition(run["id"], R.WAITING_FOR_APPROVAL, step=Step.WAITING_FOR_APPROVAL)
                self._ack(msg["id"])
            return "waiting"
        now = self.clock.now()
        aid = new_id("apr")
        marker = payload["marker"]
        ahash = compute_action_hash(payload["action"], payload["scope"], {"marker": marker})
        with self.s.tx():
            self.s.x("INSERT INTO approvals(id,schema_version,run_id,action,scope,risk_level,action_hash,requester,reason,expires_at,status,"
                     "provider,correlation_id,created_at,updated_at,dev_only) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (aid, SCHEMA_VERSION, run["id"], payload["action"], payload["scope"], payload["risk_level"], ahash,
                      payload["requester"], payload["reason"], iso(now + timedelta(seconds=payload["approval_ttl_s"])), "PENDING",
                      self.gov.name, run["correlation_id"], iso(now), iso(now), int(not self.gov.is_production)))
            self.s.x("UPDATE workflow_runs SET approval_id=? WHERE id=?", (aid, run["id"]))
            self._transition(run["id"], R.WAITING_FOR_APPROVAL, step=Step.WAITING_FOR_APPROVAL)
            self._event("approval", aid, "approval.requested", run_id=run["id"], corr=run["correlation_id"],
                        detail={"scope": payload["scope"], "risk": payload["risk_level"], "provider": self.gov.name})
            self._ack(msg["id"])
        self._register_with_governance(aid)
        return "waiting"

    def _register_with_governance(self, approval_id):
        ap = self.s.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not ap or ap["provider_ref"] or ap["status"] != "PENDING":
            return
        try:
            if not self.gov.configured():
                raise DecisionRejected("governance_unconfigured", self.gov.status_reason())
            ref = self.gov.create_request(ap)
            self.s.x("UPDATE approvals SET provider_ref=?, blocked_reason=NULL, updated_at=? WHERE id=?", (ref, self._now(), approval_id))
        except DecisionRejected as e:
            # FAIL CLOSED: the workflow stays WAITING_FOR_APPROVAL; nothing is bypassed.
            self.s.x("UPDATE approvals SET blocked_reason=?, updated_at=? WHERE id=?", (redact(e.code), self._now(), approval_id))

    def _do_execute(self, run, msg):
        """Returns True to continue to the next step, False if the message was fully handled."""
        payload = self._payload(run)
        # fail closed: re-check governance state and binding immediately before the action
        if run["requires_approval"]:
            ap = self.s.one("SELECT * FROM approvals WHERE id=?", (run["approval_id"],)) if run["approval_id"] else None
            if not ap or ap["status"] != "GRANTED":
                self._fail_permanent(run, msg, "approval_revoked" if ap and ap["status"] == "REVOKED" else "policy",
                                     "approval not in GRANTED state at execution time")
                return False
            if ap["action_hash"] != compute_action_hash(payload["action"], payload["scope"], {"marker": payload["marker"]}) \
                    or ap["run_id"] != run["id"] or ap["action"] != payload["action"] or ap["scope"] != payload["scope"]:
                self._fail_permanent(run, msg, "policy", "approval does not match the action payload (hash/scope mismatch)")
                return False
        with self.s.tx():
            self.s.x("UPDATE workflow_runs SET attempts=attempts+1, retry_started_at=COALESCE(retry_started_at,?) WHERE id=?", (self._now(), run["id"]))
            run = self.get_run(run["id"])
            aid = new_id("att")
            self.s.x("INSERT INTO workflow_attempts(id,run_id,step,attempt_no,started_at,outcome,correlation_id) VALUES(?,?,?,?,?,?,?)",
                     (aid, run["id"], Step.EXECUTE, run["attempts"], self._now(), "STARTED", run["correlation_id"]))
        sim = payload.get("simulate", {})
        try:
            if sim.get("slow_s", 0) > self.cfg.step_timeout_s:
                raise StepError("timeout", f"step exceeded {self.cfg.step_timeout_s}s timeout", True)
            done_in_base = run["attempts"] - run["attempt_base"]
            if done_in_base <= sim.get("fail_times", 0):
                kind = sim.get("kind", "transient")
                raise StepError("transient" if kind == "transient" else "permanent", f"simulated {kind} failure", kind == "transient")
            with self.s.tx():  # idempotent side effect: INSERT OR IGNORE on a deterministic key
                key = f"{run['id']}:{payload['action']}"
                cur = self.s.x("INSERT OR IGNORE INTO side_effects(key,run_id,action,marker,created_at) VALUES(?,?,?,?,?)",
                               (key, run["id"], payload["action"], payload["marker"], self._now()))
                self.s.x("UPDATE workflow_attempts SET finished_at=?, outcome='OK' WHERE id=?", (self._now(), aid))
                if cur.rowcount == 0:
                    self._event("run", run["id"], "action.duplicate_suppressed", run_id=run["id"], corr=run["correlation_id"])
        except StepError as e:
            self._handle_failure(run, msg, aid, e)
            return False
        self._set_step(run["id"], Step.NOTIFY)
        return True

    def _fail_permanent(self, run, msg, error_class, error):
        with self.s.tx():
            if run["status"] not in (R.RUNNING, R.QUEUED, R.RETRY_WAIT):
                pass
            self._transition(run["id"], R.FAILED, failure_class=error_class, last_error=redact(error), detail={"error_class": error_class})
            self._ack(msg["id"])

    def _handle_failure(self, run, msg, attempt_id, err):
        now = self.clock.now()
        with self.s.tx():
            outcome = "RETRY" if err.transient else "FAILED"
            self.s.x("UPDATE workflow_attempts SET finished_at=?, outcome=?, error_class=?, error=? WHERE id=?",
                     (iso(now), outcome, err.error_class, redact(str(err)), attempt_id))
            if not err.transient:
                self._fail_permanent(run, msg, err.error_class, str(err))
                return
            used = run["attempts"] - run["attempt_base"]
            delay = self.backoff.delay(used)
            started = parse_iso(run["retry_started_at"]) if run["retry_started_at"] else now
            elapsed = (now - started).total_seconds()
            if used >= self.cfg.max_attempts or elapsed + delay > self.cfg.max_retry_window_s:
                self._dead_letter(msg, run, "transient_exhausted", f"retries exhausted after {used} attempts: {err}")
                return
            nxt = iso(now + timedelta(seconds=delay))
            self._transition(run["id"], R.RETRY_WAIT, next_retry_at=nxt, last_error=redact(str(err)), detail={"attempt": used, "delay_s": round(delay, 2)})
            self._release(msg["id"], nxt)
            self._event("run", run["id"], "retry.scheduled", run_id=run["id"], corr=run["correlation_id"], detail={"attempt": used, "next_retry_at": nxt})

    def _do_notify(self, run, msg):
        payload = self._payload(run)
        n = payload["notify"]
        with self.s.tx():   # OUTBOX: notification intent + completion commit atomically
            self._create_notification(run_id=run["id"], channel=n["channel"], destination=n["destination"], mode=n["mode"],
                                      template="workflow.completed", corr=run["correlation_id"], confirmed_real=False,
                                      idem=f"{run['id']}:notify")
            self._transition(run["id"], R.SUCCEEDED, step=Step.COMPLETE)
            self._ack(msg["id"])

    # ------------------------------------------------------------------ approvals
    def submit_decision(self, raw, actor="governance-callback"):
        """Validate (strict schema + signature + binding) then record evidence and resume EXACTLY once."""
        try:
            env = C.validate("ApprovalDecision", raw)
        except ValidationError as e:
            self._event("approval", "unknown", "approval.decision_rejected", detail={"reason": "malformed", "error": str(e)[:200]}, actor=actor)
            raise DecisionRejected("malformed", str(e))
        ap = self.s.one("SELECT * FROM approvals WHERE id=?", (env["approval_id"],))
        if not ap:
            self._event("approval", env["approval_id"], "approval.decision_rejected", detail={"reason": "unknown_approval"}, actor=actor)
            raise DecisionRejected("unknown_approval")
        now = self.clock.now()
        try:
            v = self.gov.verify_decision(env, ap, now)
            with self.s.tx():
                ap = self.s.one("SELECT * FROM approvals WHERE id=?", (ap["id"],))
                if self.s.one("SELECT 1 FROM decision_nonces WHERE event_id=?", (v["event_id"],)):
                    raise DecisionRejected("replayed_event")
                if ap["status"] == "PENDING" and ap["expires_at"] <= iso(now):
                    self._expire_approval(ap)
                    raise DecisionRejected("approval_expired")
                self._apply_decision(ap, v, now, actor)
                self.s.x("INSERT INTO decision_nonces(event_id,approval_id,received_at) VALUES(?,?,?)", (v["event_id"], ap["id"], iso(now)))
        except DecisionRejected as e:
            self._event("approval", ap["id"], "approval.decision_rejected", run_id=ap["run_id"], corr=ap["correlation_id"],
                        detail={"reason": e.code}, actor=actor)
            raise
        return self.s.one("SELECT * FROM approvals WHERE id=?", (ap["id"],))

    def _apply_decision(self, ap, v, now, actor):
        run = self.get_run(ap["run_id"])
        stamp = (iso(now), v["lineage_ref"], int(not self.gov.is_production), iso(now), ap["id"])
        if v["decision"] == "granted":
            if ap["status"] != "PENDING" or run["status"] != R.WAITING_FOR_APPROVAL:
                raise DecisionRejected("not_pending", f"approval {ap['status']}, run {run['status']}")
            self.s.x("UPDATE approvals SET status='GRANTED', decided_at=?, decision_ref=?, dev_only=?, updated_at=? WHERE id=?", stamp)
            self._event("approval", ap["id"], "approval.granted", run_id=run["id"], corr=run["correlation_id"], actor=actor,
                        detail={"decision_ref": v["lineage_ref"], "dev_only": not self.gov.is_production})
            self._transition(run["id"], R.QUEUED, step=Step.EXECUTE, actor=actor)
            self._enqueue(run["id"], "resume", f"run:{run['id']}:resume:{ap['id']}", run["correlation_id"])
        elif v["decision"] == "rejected":
            if ap["status"] != "PENDING":
                raise DecisionRejected("not_pending")
            self.s.x("UPDATE approvals SET status='REJECTED', decided_at=?, decision_ref=?, dev_only=?, updated_at=? WHERE id=?", stamp)
            self._event("approval", ap["id"], "approval.rejected", run_id=run["id"], corr=run["correlation_id"], actor=actor)
            if run["status"] == R.WAITING_FOR_APPROVAL:
                self._transition(run["id"], R.FAILED, failure_class="approval_rejected", last_error="approval rejected", actor=actor)
        else:  # revoked
            if ap["status"] not in ("PENDING", "GRANTED"):
                raise DecisionRejected("not_revocable")
            self.s.x("UPDATE approvals SET status='REVOKED', decided_at=?, decision_ref=?, dev_only=?, updated_at=? WHERE id=?", stamp)
            self._event("approval", ap["id"], "approval.revoked", run_id=run["id"], corr=run["correlation_id"], actor=actor)
            if run["status"] in (R.WAITING_FOR_APPROVAL, R.QUEUED, R.RETRY_WAIT, R.RUNNING):
                if run["status"] == R.RUNNING:
                    self._transition(run["id"], R.QUEUED, actor=actor)
                self._transition(run["id"], R.FAILED, failure_class="approval_revoked", last_error="approval revoked", actor=actor)
                self.s.x("UPDATE queue_messages SET status='DONE', updated_at=? WHERE run_id=? AND status IN ('VISIBLE','IN_FLIGHT')", (self._now(), run["id"]))

    def _expire_approval(self, ap):
        self.s.x("UPDATE approvals SET status='EXPIRED', updated_at=? WHERE id=? AND status='PENDING'", (self._now(), ap["id"]))
        self._event("approval", ap["id"], "approval.expired", run_id=ap["run_id"], corr=ap["correlation_id"])
        run = self.get_run(ap["run_id"])
        if run["status"] == R.WAITING_FOR_APPROVAL:
            self._transition(run["id"], R.FAILED, failure_class="approval_expired", last_error="approval expired")

    def list_approvals(self, status=None):
        sql, p = "SELECT * FROM approvals", []
        if status:
            sql += " WHERE status=?"; p.append(status)
        return self.s.q(sql + " ORDER BY created_at DESC LIMIT 200", p)

    # ------------------------------------------------------------------ sweep / recovery
    def sweep(self):
        now = iso(self.clock.now())
        with self.s.tx():
            for ap in self.s.q("SELECT * FROM approvals WHERE status='PENDING' AND expires_at<=?", (now,)):
                self._expire_approval(ap)
            for ap in self.s.q("SELECT id FROM approvals WHERE status='PENDING' AND provider_ref IS NULL"):
                self._register_with_governance(ap["id"])
        # authenticated polling for real governance providers
        for ap in self.s.q("SELECT * FROM approvals WHERE status='PENDING' AND provider_ref IS NOT NULL"):
            try:
                raw = self.gov.fetch_decision(ap)
                if raw:
                    self.submit_decision(raw, actor="governance-poll")
            except (DecisionRejected, ValidationError):
                pass
        self.reconcile_stale_sending()

    def recover(self):
        """Restart recovery: return expired leases to the queue; re-enqueue RUNNING runs that lost their message."""
        n = 0
        with self.s.tx():
            now = self._now()
            for m in self.s.q("SELECT id,run_id FROM queue_messages WHERE status='IN_FLIGHT'"):
                self.s.x("UPDATE queue_messages SET status='VISIBLE', leased_until=NULL, updated_at=? WHERE id=?", (now, m["id"]))
                self._event("queue", m["id"], "queue.recovered_on_restart", run_id=m["run_id"]); n += 1
            for r in self.s.q("SELECT * FROM workflow_runs WHERE status='RUNNING'"):
                live = self.s.one("SELECT 1 FROM queue_messages WHERE run_id=? AND status IN ('VISIBLE','IN_FLIGHT')", (r["id"],))
                if not live:   # message lost: re-enqueue under a fresh dedupe key
                    self._event("run", r["id"], "run.recovered", run_id=r["id"], corr=r["correlation_id"], actor="recovery")
                    self._enqueue(r["id"], "recovery", f"run:{r['id']}:recover:{now}", r["correlation_id"]); n += 1
        self.reconcile_stale_sending(force=True)
        return n

    def stuck_runs(self):
        cutoff = iso(self.clock.now() - timedelta(seconds=self.cfg.stuck_run_s))
        return self.s.q("SELECT * FROM workflow_runs WHERE status IN ('RUNNING','QUEUED') AND updated_at<? ORDER BY updated_at", (cutoff,))

    # ------------------------------------------------------------------ DLQ / redrive
    def list_dlq(self, status=None):
        sql, p = "SELECT * FROM dead_letters", []
        if status:
            sql += " WHERE status=?"; p.append(status)
        return self.s.q(sql + " ORDER BY created_at DESC LIMIT 200", p)

    def get_dlq(self, dlq_id):
        d = self.s.one("SELECT * FROM dead_letters WHERE id=?", (dlq_id,))
        if not d:
            raise NotFound(dlq_id)
        d["attempt_history"] = jload(d.pop("attempt_history_json"), [])
        d["related_events"] = self.s.q("SELECT * FROM events WHERE entity_id IN (?,?) ORDER BY seq", (d["entity_id"], d["queue_message_id"] or ""))
        return d

    def redrive(self, ids, actor, dry_run=True, confirm=False):
        """Bounded, audited redrive. Preserves event identity and dedupe key; history is never erased."""
        ids = list(dict.fromkeys(ids))
        if len(ids) > self.cfg.redrive_max_per_call:
            raise Refused(f"at most {self.cfg.redrive_max_per_call} items per call")
        hour_ago = iso(self.clock.now() - timedelta(hours=1))
        recent = self.s.one("SELECT COUNT(*) c FROM events WHERE type='queue.redriven' AND ts>=?", (hour_ago,))["c"]
        plan = []
        for did in ids:
            d = self.s.one("SELECT * FROM dead_letters WHERE id=?", (did,))
            reason = None
            if not d:
                reason = "not found"
            elif d["status"] != "OPEN":
                reason = f"already {d['status']}"
            elif d["error_class"] == "poison":
                reason = "poison message cannot be redriven; fix or discard the payload"
            elif d["redrive_count"] >= self.cfg.redrive_loop_limit:
                reason = f"redrive loop guard: already redriven {d['redrive_count']} times"
            plan.append({"id": did, "eligible": reason is None, "reason": reason,
                         "event_id": d["event_id"] if d else None, "kind": d["kind"] if d else None})
        eligible = [p for p in plan if p["eligible"]]
        if recent + len(eligible) > self.cfg.redrive_max_per_hour and not dry_run:
            raise Refused("hourly redrive rate cap would be exceeded")
        result = {"dry_run": dry_run, "plan": plan, "redriven": []}
        if dry_run:
            self.audit(actor, "dlq.redrive_dry_run", "dlq", ",".join(ids)[:100], {"eligible": len(eligible)})
            return result
        if confirm is not True:
            raise Refused("confirmation required")
        for p in eligible:
            with self.s.tx():
                d = self.s.one("SELECT * FROM dead_letters WHERE id=?", (p["id"],))
                now = self._now()
                if d["kind"] == "notification":
                    n = self.s.one("SELECT * FROM notifications WHERE id=?", (d["entity_id"],))
                    check_notif(n["status"], N.QUEUED)
                    self.s.x("UPDATE notifications SET status='QUEUED', attempt_base=attempts, first_attempt_at=NULL, next_attempt_at=NULL, updated_at=? WHERE id=?", (now, n["id"]))
                    self._event("notification", n["id"], "notification.redriven", run_id=n["run_id"], frm=N.DEAD_LETTERED, to=N.QUEUED, actor=actor, corr=n["correlation_id"])
                else:
                    m = self.s.one("SELECT * FROM queue_messages WHERE id=?", (d["queue_message_id"],))
                    self.s.x("UPDATE queue_messages SET status='VISIBLE', receive_base=receive_count, redrive_count=redrive_count+1, visible_at=?, leased_until=NULL, updated_at=? WHERE id=?", (now, now, m["id"]))
                    if d["kind"] == "workflow":
                        r = self.get_run(d["entity_id"])
                        self._transition(r["id"], R.QUEUED, actor=actor, attempt_base=r["attempts"], retry_started_at=None, failure_class=None, last_error=None)
                self.s.x("UPDATE dead_letters SET status='REDRIVEN', redriven_at=?, redrive_count=redrive_count+1 WHERE id=?", (now, d["id"]))
                self._event("queue", d["queue_message_id"] or d["entity_id"], "queue.redriven", run_id=d["entity_id"] if d["kind"] == "workflow" else None,
                            actor=actor, detail={"dlq_id": d["id"], "event_id": d["event_id"]}, corr=d["correlation_id"])
                self.audit(actor, "dlq.redrive", "dlq", d["id"], {"event_id": d["event_id"]})
                result["redriven"].append(d["id"])
        return result

    # ------------------------------------------------------------------ notifications
    def _provider_for(self, channel, mode):
        for p in self.providers:
            if p.mode == mode and channel in p.channels:
                return p
        return None

    def create_notification(self, channel, destination, mode="LOCAL", template="test", corr=None, run_id=None,
                            confirmed_real=False, idem=None, params=None, actor="operator"):
        with self.s.tx():
            n = self._create_notification(run_id, channel, destination, mode, template, corr or new_id("corr"),
                                          confirmed_real, idem, params)
            self.audit(actor, "notification.create", "notification", n["id"], {"mode": mode, "channel": channel})
            return n

    def _create_notification(self, run_id, channel, destination, mode, template, corr, confirmed_real, idem, params=None):
        if channel not in C.CHANNELS or mode not in C.MODES:
            raise ValidationError("invalid channel/mode")
        dh = sha256_hex(f"{channel}:{destination}".lower())
        idem = idem or new_id("nidem")
        ex = self.s.one("SELECT * FROM notifications WHERE idempotency_key=?", (idem,))
        if ex:
            self._event("notification", ex["id"], "notification.duplicate_ignored", run_id=run_id, corr=corr)
            return ex
        now, nid = self._now(), new_id("ntf")
        status, reason = N.CREATED, None
        suppress = self._policy_suppression(channel, mode, dh)
        if suppress:
            status, reason = N.SUPPRESSED, suppress
        self.s.x("INSERT INTO notifications(id,schema_version,run_id,correlation_id,channel,mode,destination,destination_hash,destination_masked,"
                 "template,params_json,status,suppress_reason,confirmed_real,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (nid, SCHEMA_VERSION, run_id, corr, channel, mode, destination, dh, mask_destination(destination), template,
                  jdump(params or {}), status, reason, int(confirmed_real), idem, now, now))
        self._event("notification", nid, "notification.created" if not reason else "notification.suppressed", run_id=run_id, corr=corr,
                    to=status, detail={"channel": channel, "mode": mode, "reason": reason})
        return self.s.one("SELECT * FROM notifications WHERE id=?", (nid,))

    def set_consent(self, channel, destination, status, actor):
        if status not in ("opted_in", "opted_out"):
            raise ValidationError("status must be opted_in or opted_out")
        dh = sha256_hex(f"{channel}:{destination}".lower())
        self.s.x("INSERT INTO consents(destination_hash,channel,status,updated_at) VALUES(?,?,?,?) ON CONFLICT(destination_hash,channel) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
                 (dh, channel, status, self._now()))
        self.audit(actor, "consent." + status, "consent", dh[:16], {"channel": channel})

    def _policy_suppression(self, channel, mode, dh):
        c = self.s.one("SELECT status FROM consents WHERE destination_hash=? AND channel=?", (dh, channel))
        if c and c["status"] == "opted_out":
            return "opted_out"
        if mode == "REAL" and channel in ("sms", "whatsapp") and not (c and c["status"] == "opted_in"):
            return "no_recorded_consent"
        since = iso(self.clock.now() - timedelta(seconds=self.cfg.storm_window_s))
        cnt = self.s.one("SELECT COUNT(*) c FROM notifications WHERE destination_hash=? AND created_at>=? AND status!='SUPPRESSED'", (dh, since))["c"]
        if cnt >= self.cfg.storm_limit:
            return "storm_suppression"
        return None

    def _health(self, provider):
        h = self.s.one("SELECT * FROM provider_health WHERE provider=?", (provider,))
        if not h:
            self.s.x("INSERT INTO provider_health(provider,state,updated_at) VALUES(?,?,?)", (provider, "CLOSED", self._now()))
            h = self.s.one("SELECT * FROM provider_health WHERE provider=?", (provider,))
        return h

    def _breaker_record(self, provider, ok, error=None):
        h = self._health(provider)
        now = self._now()
        if ok:
            self.s.x("UPDATE provider_health SET state='CLOSED', consecutive_failures=0, cooldown_until=NULL, last_success_at=?, updated_at=? WHERE provider=?", (now, now, provider))
            return
        f = h["consecutive_failures"] + 1
        if f >= self.cfg.breaker_threshold:
            until = iso(self.clock.now() + timedelta(seconds=self.cfg.breaker_cooldown_s))
            self.s.x("UPDATE provider_health SET state='OPEN', consecutive_failures=?, opened_at=?, cooldown_until=?, last_failure_at=?, last_error=?, updated_at=? WHERE provider=?",
                     (f, now, until, now, redact(error), now, provider))
            self._event("provider", provider, "provider.circuit_open", detail={"cooldown_until": until})
        else:
            self.s.x("UPDATE provider_health SET consecutive_failures=?, last_failure_at=?, last_error=?, updated_at=? WHERE provider=?", (f, now, redact(error), now, provider))

    def _suppress(self, n, reason):
        check_notif(n["status"], N.SUPPRESSED)
        self.s.x("UPDATE notifications SET status='SUPPRESSED', suppress_reason=?, updated_at=? WHERE id=?", (reason, self._now(), n["id"]))
        self._event("notification", n["id"], "notification.suppressed", run_id=n["run_id"], corr=n["correlation_id"], frm=n["status"], to=N.SUPPRESSED, detail={"reason": reason})

    def deliver_notifications(self, limit=20):
        now = self._now()
        rows = self.s.q("SELECT * FROM notifications WHERE status IN ('CREATED','QUEUED','RETRYING') AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY created_at LIMIT ?", (now, limit))
        done = 0
        for n in rows:
            done += self._deliver_one(n["id"])
        return done

    def _deliver_one(self, nid):
        prov_obj = None
        with self.s.tx():
            n = self.s.one("SELECT * FROM notifications WHERE id=?", (nid,))
            if n["status"] not in (N.CREATED, N.QUEUED, N.RETRYING):
                return 0
            sup = self._policy_suppression(n["channel"], n["mode"], n["destination_hash"]) if n["attempts"] == n["attempt_base"] else None
            c = self.s.one("SELECT status FROM consents WHERE destination_hash=? AND channel=?", (n["destination_hash"], n["channel"]))
            if c and c["status"] == "opted_out":
                self._suppress(n, "opted_out"); return 0
            if sup in ("no_recorded_consent",):
                self._suppress(n, sup); return 0
            prov_obj = self._provider_for(n["channel"], n["mode"])
            if n["mode"] == "REAL" and not n["confirmed_real"]:
                self._suppress(n, "real_send_not_confirmed"); return 0
            if prov_obj is None or not prov_obj.configured():
                reason = "no provider for channel/mode" if prov_obj is None else prov_obj.status_reason()
                self._fail_notification(n, "unconfigured", reason); return 1
            err = prov_obj.validate_destination(n["channel"], n["destination"]) if n["mode"] == "REAL" else None
            if err:
                self._fail_notification(n, "policy", err); return 1
            h = self._health(prov_obj.name)
            if h["state"] == "OPEN" and h["cooldown_until"] and h["cooldown_until"] > self._now():
                self.s.x("UPDATE notifications SET next_attempt_at=?, updated_at=? WHERE id=?", (h["cooldown_until"], self._now(), nid))
                self._event("notification", nid, "notification.deferred_circuit_open", run_id=n["run_id"], corr=n["correlation_id"])
                return 0
            minute_ago = iso(self.clock.now() - timedelta(seconds=60))
            recent = self.s.one("SELECT COUNT(*) c FROM notification_attempts WHERE provider=? AND started_at>=?", (prov_obj.name, minute_ago))["c"]
            if recent >= self.cfg.notify_rate_per_min:
                self.s.x("UPDATE notifications SET next_attempt_at=?, updated_at=? WHERE id=?", (self.clock.plus_iso(10), self._now(), nid))
                self._event("notification", nid, "notification.deferred_rate_limit", run_id=n["run_id"], corr=n["correlation_id"])
                return 0
            if h["state"] == "OPEN":
                self.s.x("UPDATE provider_health SET state='HALF_OPEN', updated_at=? WHERE provider=?", (self._now(), prov_obj.name))
            check_notif(n["status"], N.SENDING)
            att_no = n["attempts"] + 1
            self.s.x("UPDATE notifications SET status='SENDING', attempts=?, provider=?, first_attempt_at=COALESCE(first_attempt_at,?), updated_at=? WHERE id=?",
                     (att_no, prov_obj.name, self._now(), self._now(), nid))
            aid = new_id("natt")
            self.s.x("INSERT INTO notification_attempts(id,schema_version,notification_id,attempt_no,started_at,outcome,provider,correlation_id) VALUES(?,?,?,?,?,?,?,?)",
                     (aid, SCHEMA_VERSION, nid, att_no, self._now(), "SENDING", prov_obj.name, n["correlation_id"]))
            self._event("notification", nid, "notification.sending", run_id=n["run_id"], frm=n["status"], to=N.SENDING, corr=n["correlation_id"], detail={"attempt": att_no, "provider": prov_obj.name})
            n = self.s.one("SELECT * FROM notifications WHERE id=?", (nid,))
        # ---- provider call happens OUTSIDE the DB transaction
        try:
            res = prov_obj.send(n)
        except Exception as e:  # provider bug: treat as ambiguous (never assume not-sent)
            from .providers import ProviderResult, AMBIGUOUS
            res = ProviderResult(AMBIGUOUS, error_class="ambiguous", error=type(e).__name__)
        self._record_result(n, aid, prov_obj, res)
        return 1

    def _fail_notification(self, n, error_class, error):
        check_notif(n["status"], N.FAILED)
        self.s.x("UPDATE notifications SET status='FAILED', error_class=?, last_error=?, updated_at=? WHERE id=?", (error_class, redact(error), self._now(), n["id"]))
        self._event("notification", n["id"], "notification.failed", run_id=n["run_id"], corr=n["correlation_id"], to=N.FAILED, detail={"error_class": error_class, "error": redact(error)})

    def _record_result(self, n, aid, prov, res):
        from .providers import ACCEPTED, TRANSIENT, PERMANENT, AMBIGUOUS
        now = self.clock.now()
        with self.s.tx():
            cur = self.s.one("SELECT * FROM notifications WHERE id=?", (n["id"],))
            if cur["status"] != N.SENDING:   # reconciled/changed meanwhile; keep attempt history only
                self.s.x("UPDATE notification_attempts SET finished_at=?, outcome=?, provider_message_id=?, error_class=?, error=? WHERE id=?",
                         (iso(now), "LATE_" + res.outcome, res.message_id, res.error_class, res.error, aid))
                return
            self.s.x("UPDATE notification_attempts SET finished_at=?, outcome=?, provider_message_id=?, error_class=?, error=? WHERE id=?",
                     (iso(now), res.outcome, res.message_id, res.error_class, res.error, aid))
            if res.outcome == ACCEPTED:
                self.s.x("UPDATE notifications SET status='ACCEPTED', provider_message_id=?, last_error=NULL, error_class=NULL, updated_at=? WHERE id=?", (res.message_id, iso(now), n["id"]))
                self._event("notification", n["id"], "notification.accepted", run_id=n["run_id"], corr=n["correlation_id"], frm=N.SENDING, to=N.ACCEPTED, detail={"provider": prov.name, "mode": prov.mode})
                self._breaker_record(prov.name, True)
                self._reapply_unmatched(res.message_id)
            elif res.outcome == AMBIGUOUS:
                self.s.x("UPDATE notifications SET status='UNKNOWN', error_class='ambiguous', last_error=?, updated_at=? WHERE id=?", (redact(res.error), iso(now), n["id"]))
                self._event("notification", n["id"], "notification.unknown", run_id=n["run_id"], corr=n["correlation_id"], frm=N.SENDING, to=N.UNKNOWN, detail={"note": "outcome ambiguous; not resent automatically"})
            elif res.outcome == PERMANENT:
                self.s.x("UPDATE notifications SET status='FAILED', error_class=?, last_error=?, updated_at=? WHERE id=?", (res.error_class, redact(res.error), iso(now), n["id"]))
                self._event("notification", n["id"], "notification.failed", run_id=n["run_id"], corr=n["correlation_id"], frm=N.SENDING, to=N.FAILED, detail={"error_class": res.error_class})
            else:  # TRANSIENT
                self._breaker_record(prov.name, False, res.error)
                used = cur["attempts"] - cur["attempt_base"]
                started = parse_iso(cur["first_attempt_at"]) if cur["first_attempt_at"] else now
                delay = self.backoff.delay(used)
                if used >= self.cfg.notif_max_attempts or (now - started).total_seconds() + delay > self.cfg.notif_max_window_s:
                    self.s.x("UPDATE notifications SET status='DEAD_LETTERED', error_class='transient_exhausted', last_error=?, updated_at=? WHERE id=?", (redact(res.error), iso(now), n["id"]))
                    did = new_id("dlq")
                    hist = [{"attempt_no": a["attempt_no"], "outcome": a["outcome"], "error_class": a["error_class"]} for a in self.s.q("SELECT * FROM notification_attempts WHERE notification_id=? ORDER BY attempt_no", (n["id"],))]
                    self.s.x("INSERT INTO dead_letters(id,schema_version,kind,entity_id,event_id,payload_hash,payload_ref,error_class,error,attempt_history_json,status,created_at,correlation_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (did, SCHEMA_VERSION, "notification", n["id"], new_id("qe"), sha256_hex(n["idempotency_key"]), f"notifications/{n['id']}", "transient_exhausted", redact(res.error), jdump(hist), "OPEN", iso(now), n["correlation_id"]))
                    self._event("notification", n["id"], "notification.dead_lettered", run_id=n["run_id"], corr=n["correlation_id"], frm=N.SENDING, to=N.DEAD_LETTERED, detail={"dlq_id": did})
                else:
                    nxt = iso(now + timedelta(seconds=delay))
                    self.s.x("UPDATE notifications SET status='RETRYING', next_attempt_at=?, error_class='transient', last_error=?, updated_at=? WHERE id=?", (nxt, redact(res.error), iso(now), n["id"]))
                    self._event("notification", n["id"], "notification.retrying", run_id=n["run_id"], corr=n["correlation_id"], frm=N.SENDING, to=N.RETRYING, detail={"next_attempt_at": nxt, "attempt": used})

    def reconcile_stale_sending(self, force=False):
        """Conservative: a SENDING attempt with no recorded result may or may not have reached the provider -> UNKNOWN, never resend."""
        cutoff = iso(self.clock.now() - timedelta(seconds=0 if force else self.cfg.notif_stale_sending_s))
        out = 0
        with self.s.tx():
            for n in self.s.q("SELECT * FROM notifications WHERE status='SENDING' AND updated_at<=?", (cutoff,)):
                self.s.x("UPDATE notifications SET status='UNKNOWN', error_class='ambiguous', last_error='stale SENDING reconciled conservatively', updated_at=? WHERE id=?", (self._now(), n["id"]))
                self.s.x("UPDATE notification_attempts SET outcome='UNKNOWN_STALE', finished_at=? WHERE notification_id=? AND outcome='SENDING'", (self._now(), n["id"]))
                self._event("notification", n["id"], "notification.reconciled_unknown", run_id=n["run_id"], corr=n["correlation_id"], frm=N.SENDING, to=N.UNKNOWN, actor="reconciler")
                out += 1
        return out

    def replay_notification(self, nid, actor, confirm=False):
        """Manual replay of UNKNOWN / DEAD_LETTERED notification. New attempt row; old history preserved. May duplicate for UNKNOWN."""
        if confirm is not True:
            raise Refused("confirmation required")
        with self.s.tx():
            n = self.s.one("SELECT * FROM notifications WHERE id=?", (nid,))
            if not n:
                raise NotFound(nid)
            if n["status"] not in (N.UNKNOWN, N.DEAD_LETTERED):
                raise Refused(f"only UNKNOWN or DEAD_LETTERED notifications can be replayed (was {n['status']})")
            check_notif(n["status"], N.QUEUED)
            self.s.x("UPDATE notifications SET status='QUEUED', attempt_base=attempts, first_attempt_at=NULL, next_attempt_at=NULL, updated_at=? WHERE id=?", (self._now(), nid))
            if n["status"] == N.DEAD_LETTERED:
                self.s.x("UPDATE dead_letters SET status='REDRIVEN', redriven_at=?, redrive_count=redrive_count+1 WHERE entity_id=? AND status='OPEN'", (self._now(), nid))
            self._event("notification", nid, "notification.replayed", run_id=n["run_id"], corr=n["correlation_id"], frm=n["status"], to=N.QUEUED, actor=actor, detail={"from": n["status"]})
            self.audit(actor, "notification.replay", "notification", nid, {"from": n["status"]})

    def apply_receipt(self, provider, provider_message_id, provider_event_id, status, provider_ts=None, verified=False, source="webhook"):
        """Idempotent receipt application. Duplicate / late / out-of-order / unmatched receipts are all handled."""
        status = status.lower()
        if status not in ("sent", "delivered", "read", "failed"):
            raise ValidationError("unknown receipt status")
        with self.s.tx():
            now = self._now()
            rid = new_id("rcpt")
            cur = self.s.x("INSERT OR IGNORE INTO delivery_receipts(id,schema_version,provider,provider_event_id,provider_message_id,status,provider_ts,received_at,verified,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (rid, SCHEMA_VERSION, provider, provider_event_id, provider_message_id, status, provider_ts, now, int(verified), source))
            if cur.rowcount == 0:
                return "duplicate"
            return self._apply_receipt_row(rid)

    def _apply_receipt_row(self, rid):
        r = self.s.one("SELECT * FROM delivery_receipts WHERE id=?", (rid,))
        n = self.s.one("SELECT * FROM notifications WHERE provider_message_id=?", (r["provider_message_id"],))
        if not n:
            self.s.x("UPDATE delivery_receipts SET note='unmatched' WHERE id=?", (rid,))
            return "unmatched"
        self.s.x("UPDATE delivery_receipts SET notification_id=? WHERE id=?", (n["id"], rid))
        if n["mode"] == "REAL" and not r["verified"]:
            self.s.x("UPDATE delivery_receipts SET note='rejected: unverified receipt for REAL notification' WHERE id=?", (rid,))
            return "rejected_unverified"
        rank = {"sent": 1, "delivered": 2, "read": 3}
        prev = (n["receipt_state"] or "").lower()
        if prev in rank and r["status"] in rank and rank[r["status"]] <= rank[prev]:
            self.s.x("UPDATE delivery_receipts SET note='out_of_order_ignored' WHERE id=?", (rid,))
            return "out_of_order_ignored"
        if n["status"] in (N.FAILED, N.DEAD_LETTERED, N.SUPPRESSED, N.DELIVERED) and r["status"] != "read":
            self.s.x("UPDATE delivery_receipts SET note='recorded_not_applied' WHERE id=?", (rid,))
            return "recorded_not_applied"
        new = {"sent": N.ACCEPTED, "delivered": N.DELIVERED, "read": N.DELIVERED, "failed": N.FAILED}[r["status"]]
        if new != n["status"]:
            try:
                check_notif(n["status"], new)
            except IllegalTransition:
                self.s.x("UPDATE delivery_receipts SET note='illegal_transition_ignored' WHERE id=?", (rid,))
                return "illegal_transition_ignored"
        self.s.x("UPDATE notifications SET status=?, receipt_state=?, delivery_verified=?, updated_at=? WHERE id=?",
                 (new, r["status"].upper(), int(bool(r["verified"])), self._now(), n["id"]))
        self.s.x("UPDATE delivery_receipts SET applied=1 WHERE id=?", (rid,))
        self._event("notification", n["id"], "notification.receipt_applied", run_id=n["run_id"], corr=n["correlation_id"], frm=n["status"], to=new,
                    detail={"receipt": r["status"], "verified": bool(r["verified"]), "source": r["source"]})
        return "applied"

    def _reapply_unmatched(self, message_id):
        if not message_id:
            return
        for r in self.s.q("SELECT id FROM delivery_receipts WHERE provider_message_id=? AND applied=0 AND note='unmatched' ORDER BY received_at", (message_id,)):
            self._apply_receipt_row(r["id"])

    def purge_expired(self):
        """Retention: scrub raw destinations from terminal notifications older than retention_days; prune old metrics."""
        cutoff = iso(self.clock.now() - timedelta(days=self.cfg.retention_days))
        with self.s.tx():
            a = self.s.x("UPDATE notifications SET destination=NULL, params_json=NULL WHERE destination IS NOT NULL AND updated_at<? AND status IN ('DELIVERED','FAILED','SUPPRESSED','DEAD_LETTERED','ACCEPTED')", (cutoff,)).rowcount
            b = self.s.x("DELETE FROM metrics WHERE ts<?", (cutoff,)).rowcount
        return {"destinations_scrubbed": a, "metrics_deleted": b}
