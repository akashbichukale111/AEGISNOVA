"""HTTP application logic (framework-free, testable without sockets)."""
import json
import os
import re
import threading
import urllib.parse

from . import SCHEMA_VERSION, __version__
from . import contracts as C
from .auth import DevTokenAuth, UnconfiguredExternalAuth, RateLimiter, ROLE_RANK
from .clock import Clock
from .config import Config
from .contracts import ValidationError
from .engine import Engine, Backoff, NotFound, Conflict, Refused, QueueFull
from .governance import DecisionRejected, select_provider, LocalDevGovernance
from .integrations import environment_label, integration_statuses, test_connection
from .observability import Observability
from .providers import LocalSink, Simulated, SnsProvider, WhatsAppCloudProvider, build_message
from .statemachine import IllegalTransition
from .store import Store, jload
from .util import mask_destination, redact

MAX_BODY = 64 * 1024
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "application/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
SEC_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
}


class HttpError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code or "error"


def _detail(row):
    d = dict(row)
    d["detail"] = jload(d.pop("detail_json", None), {}) or {}
    return d


def run_out(r):
    out = C.to_contract("WorkflowRun", r)
    p = jload(r["payload_json"], {})
    if isinstance(p.get("notify"), dict):
        p["notify"] = {**p["notify"], "destination": mask_destination(p["notify"].get("destination"))}
    out["payload"] = p
    return out


NOTIF_FIELDS = ["id", "schema_version", "run_id", "correlation_id", "channel", "mode", "destination_masked", "template", "status",
                "provider", "provider_message_id", "attempts", "next_attempt_at", "last_error", "error_class", "suppress_reason",
                "receipt_state", "delivery_verified", "idempotency_key", "created_at", "updated_at"]


def notif_out(n):
    out = {k: n.get(k) for k in NOTIF_FIELDS}
    out["delivery_verified"] = bool(out["delivery_verified"])
    out["last_error"] = redact(out["last_error"])
    return out


class App:
    def __init__(self, store, engine, obs, env, auth, gov, providers, clients=None, http=None):
        self.s, self.e, self.obs, self.env, self.auth, self.gov = store, engine, obs, env, auth, gov
        self.providers, self.clients, self.http = providers, clients or {}, http
        self.limiter = RateLimiter()
        self.cors = {o.strip() for o in env.get("AEGIS_CORS_ORIGINS", "").split(",") if o.strip()}
        self.allowed_hosts = {h.strip().lower() for h in env.get("AEGIS_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")}
        self.wa = next((p for p in providers if isinstance(p, WhatsAppCloudProvider)), None)
        self.routes = []
        self._register()

    # ---- routing -------------------------------------------------------------
    def route(self, method, pattern, role, fn, public=False):
        self.routes.append((method, re.compile("^" + pattern + "$"), role, fn, public))

    def _register(self):
        r = self.route
        r("GET", "/api/health", None, self.h_health, public=True)
        r("GET", "/api/overview", "viewer", self.h_overview)
        r("GET", "/api/workflows", "viewer", lambda ctx: (200, {"items": list(C.WORKFLOW_DEFINITIONS.values())}))
        r("GET", "/api/runs", "viewer", self.h_runs)
        r("POST", "/api/runs", "operator", self.h_run_start)
        r("GET", r"/api/runs/(?P<id>[\w.:-]+)", "viewer", self.h_run_get)
        r("POST", r"/api/runs/(?P<id>[\w.:-]+)/(?P<act>cancel|pause|resume|retry)", "operator", self.h_run_action)
        r("GET", "/api/approvals", "viewer", self.h_approvals)
        r("POST", r"/api/approvals/(?P<id>[\w.:-]+)/dev-decision", "admin", self.h_dev_decision)
        r("POST", "/api/governance/callback", None, self.h_gov_callback, public=True)
        r("GET", "/api/notifications", "viewer", self.h_notifs)
        r("GET", r"/api/notifications/(?P<id>[\w.:-]+)", "viewer", self.h_notif_get)
        r("POST", "/api/notifications/test", "operator", self.h_notif_test)
        r("POST", "/api/notifications/preview-real", "admin", self.h_real_preview)
        r("POST", "/api/notifications/send-real", "admin", self.h_real_send)
        r("POST", r"/api/notifications/(?P<id>[\w.:-]+)/replay", "admin", self.h_notif_replay)
        r("POST", "/api/consents", "admin", self.h_consent)
        r("POST", "/api/dev/simulate-receipt", "admin", self.h_sim_receipt)
        r("GET", "/api/webhooks/whatsapp", None, self.h_wa_verify, public=True)
        r("POST", "/api/webhooks/whatsapp", None, self.h_wa_webhook, public=True)
        r("GET", "/api/queue", "viewer", lambda ctx: (200, self.e.queue_stats()))
        r("GET", "/api/dlq", "viewer", self.h_dlq)
        r("GET", r"/api/dlq/(?P<id>[\w.:-]+)", "viewer", self.h_dlq_get)
        r("POST", "/api/dlq/redrive", "admin", self.h_redrive)
        r("GET", "/api/alarms", "viewer", lambda ctx: (200, {"items": self.obs.alarm_states()}))
        r("GET", "/api/alarm-events", "viewer", lambda ctx: (200, {"items": self.obs.alarm_events()}))
        r("POST", "/api/alarms/evaluate", "operator", self.h_eval)
        r("GET", "/api/metrics", "viewer", lambda ctx: (200, {"metrics": self.obs.snapshot(), "source": "local-measured"}))
        r("GET", "/api/events", "viewer", self.h_events)
        r("GET", "/api/integrations", "viewer", self.h_integrations)
        r("POST", r"/api/integrations/(?P<name>[\w-]+)/test", "operator", self.h_int_test)
        r("POST", "/api/worker/tick", "operator", self.h_tick)
        r("POST", "/api/recovery/run", "admin", self.h_recovery)

    # ---- entry point ----------------------------------------------------------
    def handle(self, method, raw_path, headers, body=b""):
        headers = {k.lower(): v for k, v in headers.items()}
        parsed = urllib.parse.urlparse(raw_path)
        path, query = parsed.path, {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        extra = dict(SEC_HEADERS)
        try:
            host = headers.get("host", "").lower()
            if host and re.sub(r":\d+$", "", host) not in self.allowed_hosts:
                raise HttpError(400, "host not allowed", "bad_host")
            origin = headers.get("origin")
            if origin and origin in self.cors:
                extra.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                              "Access-Control-Allow-Headers": "authorization, content-type", "Access-Control-Allow-Methods": "GET, POST"})
            if method == "OPTIONS":
                return 204, extra, b""
            if method == "GET" and path in STATIC:
                fname, ctype = STATIC[path]
                with open(os.path.join(STATIC_DIR, fname), "rb") as f:
                    return 200, {**extra, "Content-Type": ctype, "Cache-Control": "no-cache"}, f.read()
            if len(body) > MAX_BODY:
                raise HttpError(413, "request body too large", "too_large")
            matched = None
            for m, rx, role, fn, public in self.routes:
                mo = rx.match(path)
                if mo and m == method:
                    matched = (rx, role, fn, public, mo.groupdict()); break
                if mo and not matched:
                    matched = ("405",)
            if not matched:
                raise HttpError(404, "not found", "not_found")
            if matched[0] == "405":
                raise HttpError(405, "method not allowed", "method_not_allowed")
            _, role, fn, public, args = matched
            principal = None
            if not public:
                principal = self.auth.authenticate(headers)
                if principal is None:
                    raise HttpError(401, "authentication required", "unauthenticated")
                if ROLE_RANK[principal.role] < ROLE_RANK[role]:
                    raise HttpError(403, "insufficient role", "forbidden")
                if not self.limiter.allow(principal.name if method == "GET" else principal.name + ":w") :
                    raise HttpError(429, "rate limit exceeded", "rate_limited")
            data = None
            if method == "POST" and body:
                if "application/json" not in headers.get("content-type", "") and not (path == "/api/webhooks/whatsapp"):
                    raise HttpError(415, "content-type must be application/json", "bad_content_type")
            if method == "POST" and path != "/api/webhooks/whatsapp":
                try:
                    data = json.loads(body.decode() or "{}")
                except ValueError:
                    raise HttpError(400, "invalid JSON", "bad_json")
            ctx = {"principal": principal, "query": query, "data": data, "args": args, "raw": body, "headers": headers}
            res = fn(ctx)
            status, payload = res[0], res[1]
            if isinstance(payload, str):
                return status, {**extra, "Content-Type": "text/plain; charset=utf-8"}, payload.encode()
            return status, {**extra, "Content-Type": "application/json", "Cache-Control": "no-store"}, json.dumps(payload).encode()
        except HttpError as e:
            return self._err(e.status, e.message, e.code, extra)
        except ValidationError as e:
            return self._err(400, str(e), "validation_error", extra)
        except DecisionRejected as e:
            return self._err(422, "decision rejected", e.code, extra)
        except NotFound:
            return self._err(404, "not found", "not_found", extra)
        except (Conflict, Refused, IllegalTransition) as e:
            return self._err(409, str(e), "conflict", extra)
        except QueueFull:
            return self._err(503, "queue is full", "queue_full", extra)
        except Exception as e:  # never leak internals
            self.e._event("api", "error", "api.error", detail={"error": redact(repr(e))})
            return self._err(500, "internal error", "internal_error", extra)

    @staticmethod
    def _err(status, msg, code, extra):
        return status, {**extra, "Content-Type": "application/json", "Cache-Control": "no-store"}, json.dumps({"error": {"code": code, "message": msg}}).encode()

    # ---- handlers ----------------------------------------------------------------
    def actor(self, ctx):
        return ctx["principal"].name

    def h_health(self, ctx):
        self.s.one("SELECT 1 x")
        return 200, {"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION}

    def h_overview(self, ctx):
        return 200, self.obs.overview({**environment_label(self.env), "governance": self.gov.name,
                                       "governance_production": self.gov.is_production, "auth": self.auth.label})

    def h_runs(self, ctx):
        q = ctx["query"]
        rows = self.e.list_runs(q.get("q"), q.get("status"), q.get("workflow_type"), q.get("since"), q.get("correlation_id"), q.get("limit", 200))
        return 200, {"items": [run_out(r) for r in rows]}

    def h_run_start(self, ctx):
        run, created = self.e.start_run(ctx["data"], self.actor(ctx))
        self.e.audit(self.actor(ctx), "run.start", "run", run["id"], {"created": created}, run["id"])
        return (201 if created else 200), {"run": run_out(run), "created": created}

    def h_run_get(self, ctx):
        rid = ctx["args"]["id"]
        run = self.e.get_run(rid)
        ap = self.s.one("SELECT * FROM approvals WHERE run_id=?", (rid,))
        return 200, {"run": run_out(run), "timeline": [_detail(e) for e in self.e.timeline(rid)],
                     "attempts": self.s.q("SELECT * FROM workflow_attempts WHERE run_id=? ORDER BY attempt_no", (rid,)),
                     "approval": self._approval_out(ap) if ap else None,
                     "notifications": [notif_out(n) for n in self.s.q("SELECT * FROM notifications WHERE run_id=?", (rid,))]}

    def h_run_action(self, ctx):
        rid, act, d = ctx["args"]["id"], ctx["args"]["act"], ctx["data"] or {}
        if act == "cancel":
            if d.get("confirm") is not True:
                raise HttpError(400, "confirm:true required to cancel", "confirmation_required")
            run = self.e.cancel_run(rid, self.actor(ctx))
        elif act == "pause":
            run = self.e.pause_run(rid, self.actor(ctx))
        elif act == "resume":
            run = self.e.resume_paused(rid, self.actor(ctx))
        else:
            run = self.e.retry_run(rid, self.actor(ctx))
        return 200, {"run": run_out(run)}

    def _approval_out(self, a):
        out = C.to_contract("ApprovalRequest", a)
        out["dev_only"] = bool(a["dev_only"])
        out["label"] = "DEVELOPMENT/TEST decision - not production authorization" if a["dev_only"] else "governance provider: " + str(a["provider"])
        return out

    def h_approvals(self, ctx):
        return 200, {"items": [self._approval_out(a) for a in self.e.list_approvals(ctx["query"].get("status"))],
                     "governance": {"provider": self.gov.name, "production": self.gov.is_production, "configured": self.gov.configured(),
                                    "reason": self.gov.status_reason()}}

    def h_dev_decision(self, ctx):
        if not isinstance(self.gov, LocalDevGovernance):
            raise HttpError(404, "not available with a production governance provider", "not_found")
        d = ctx["data"] or {}
        if set(d) - {"decision"} or d.get("decision") not in C.DECISIONS:
            raise ValidationError("decision must be one of granted|rejected|revoked")
        ap = self.s.one("SELECT * FROM approvals WHERE id=?", (ctx["args"]["id"],))
        if not ap:
            raise NotFound("approval")
        env = self.gov.issue_decision(ap, d["decision"], self.e.clock.now())
        self.e.audit(self.actor(ctx), "approval.dev_decision", "approval", ap["id"], {"decision": d["decision"], "dev_only": True}, ap["run_id"])
        done = self.e.submit_decision(env, actor=self.actor(ctx) + "(dev-decision)")   # same verification path as a real callback
        return 200, {"approval": self._approval_out(done), "notice": "LOCAL DEVELOPMENT decision - not production authorization"}

    def h_gov_callback(self, ctx):
        raw = json.loads(ctx["raw"].decode() or "{}") if ctx["raw"] else {}
        if not self.gov.configured():
            raise HttpError(503, "governance provider unconfigured", "governance_unconfigured")
        ap = self.e.submit_decision(raw, actor="governance-callback")
        return 200, {"approval_id": ap["id"], "status": ap["status"]}

    def h_notifs(self, ctx):
        q = ctx["query"]
        sql, p = "SELECT * FROM notifications WHERE 1=1", []
        for col, key in (("status", "status"), ("channel", "channel"), ("mode", "mode"), ("run_id", "run_id"), ("correlation_id", "correlation_id")):
            if q.get(key):
                sql += f" AND {col}=?"; p.append(q[key])
        return 200, {"items": [notif_out(n) for n in self.s.q(sql + " ORDER BY created_at DESC LIMIT 200", p)]}

    def h_notif_get(self, ctx):
        n = self.s.one("SELECT * FROM notifications WHERE id=?", (ctx["args"]["id"],))
        if not n:
            raise NotFound("notification")
        return 200, {"notification": notif_out(n),
                     "attempts": self.s.q("SELECT * FROM notification_attempts WHERE notification_id=? ORDER BY attempt_no", (n["id"],)),
                     "receipts": [{k: v for k, v in r.items() if k != "id"} for r in self.s.q("SELECT * FROM delivery_receipts WHERE notification_id=? ORDER BY received_at", (n["id"],))],
                     "events": [_detail(e) for e in self.s.q("SELECT * FROM events WHERE entity_id=? ORDER BY seq", (n["id"],))]}

    def h_notif_test(self, ctx):
        d = C.validate("NotificationRequest", ctx["data"] or {"channel": "local_sink", "destination": "ops-sink@local.test"}) if ctx["data"] else {"channel": "local_sink", "destination": "ops-sink@local.test"}
        mode = d.get("mode", "LOCAL")
        if mode == "REAL":
            raise HttpError(400, "real sends use /api/notifications/send-real with explicit confirmation", "use_real_endpoint")
        n = self.e.create_notification(d["channel"], d["destination"], mode, "test", actor=self.actor(ctx))
        return 201, {"notification": notif_out(n), "note": "LOCAL/SIMULATED: no external message is sent"}

    def _real_provider(self, channel):
        p = self.e._provider_for(channel, "REAL")
        if p is None:
            raise HttpError(400, "no real provider exists for this channel", "no_provider")
        return p

    def h_real_preview(self, ctx):
        d = ctx["data"] or {}
        if set(d) - {"channel", "destination"}:
            raise ValidationError("unknown fields")
        p = self._real_provider(d.get("channel"))
        err = p.validate_destination(d["channel"], d.get("destination", "")) if p.configured() else None
        return 200, {"provider": p.name, "configured": p.configured(), "reason": p.status_reason(), "destination_error": err,
                     "destination_preview": d.get("destination"), "message_preview": build_message({"template": "test", "run_id": None}),
                     "warning": "A REAL message will be sent to this destination if you confirm."}

    def h_real_send(self, ctx):
        d = ctx["data"] or {}
        if set(d) - {"channel", "destination", "confirm", "confirm_destination"}:
            raise ValidationError("unknown fields")
        if d.get("confirm") != "SEND" or d.get("confirm_destination") != d.get("destination"):
            raise HttpError(400, "confirm must be 'SEND' and confirm_destination must equal destination", "confirmation_required")
        if self.env.get("AEGIS_ENABLE_REAL_SEND", "").lower() != "true":
            raise HttpError(409, "real sending is disabled (AEGIS_ENABLE_REAL_SEND is not 'true')", "real_send_disabled")
        p = self._real_provider(d["channel"])
        if not p.configured():
            raise HttpError(409, "provider unconfigured: " + p.status_reason(), "provider_unconfigured")
        err = p.validate_destination(d["channel"], d["destination"])
        if err:
            raise HttpError(400, err, "destination_rejected")
        n = self.e.create_notification(d["channel"], d["destination"], "REAL", "test", confirmed_real=True, actor=self.actor(ctx))
        return 202, {"notification": notif_out(n), "note": "Queued for the worker. ACCEPTED means provider acceptance only, not delivery."}

    def h_notif_replay(self, ctx):
        d = ctx["data"] or {}
        self.e.replay_notification(ctx["args"]["id"], self.actor(ctx), confirm=d.get("confirm") is True)
        return 200, {"status": "queued_for_replay"}

    def h_consent(self, ctx):
        d = ctx["data"] or {}
        if set(d) - {"channel", "destination", "status"} or d.get("channel") not in C.CHANNELS:
            raise ValidationError("channel, destination, status required")
        self.e.set_consent(d["channel"], d["destination"], d.get("status"), self.actor(ctx))
        return 200, {"ok": True}

    def h_sim_receipt(self, ctx):
        d = ctx["data"] or {}
        if set(d) - {"notification_id", "status"}:
            raise ValidationError("unknown fields")
        n = self.s.one("SELECT * FROM notifications WHERE id=?", (d.get("notification_id"),))
        if not n:
            raise NotFound("notification")
        if n["mode"] == "REAL" or not n["provider_message_id"]:
            raise HttpError(409, "simulated receipts apply only to accepted LOCAL/SIMULATED notifications", "not_simulated")
        res = self.e.apply_receipt(n["provider"], n["provider_message_id"], f"sim-{n['id']}-{d.get('status')}-{self.e._now()}", d.get("status", ""), None, False, "simulator")
        return 200, {"result": res, "note": "simulated receipt (verified=false)"}

    def h_wa_verify(self, ctx):
        if not self.wa or not self.wa.configured():
            raise HttpError(503, "whatsapp provider unconfigured", "provider_unconfigured")
        ch = self.wa.verify_challenge(ctx["query"])
        if ch is None:
            raise HttpError(403, "verification failed", "forbidden")
        return 200, ch

    def h_wa_webhook(self, ctx):
        if not self.wa or not self.wa.configured():
            raise HttpError(503, "whatsapp provider unconfigured", "provider_unconfigured")
        if not self.wa.verify_signature(ctx["raw"], ctx["headers"].get("x-hub-signature-256", "")):
            self.e._event("webhook", "whatsapp", "webhook.rejected", detail={"reason": "bad_signature"})
            raise HttpError(401, "invalid signature", "bad_signature")
        try:
            payload = json.loads(ctx["raw"].decode())
        except ValueError:
            raise HttpError(400, "invalid JSON", "bad_json")
        results = [self.e.apply_receipt("whatsapp-cloud", st["provider_message_id"], st["provider_event_id"], st["status"], st["provider_ts"], True, "webhook")
                   for st in self.wa.parse_statuses(payload)]
        return 200, {"processed": len(results), "results": results}

    def h_dlq(self, ctx):
        return 200, {"items": self.e.list_dlq(ctx["query"].get("status"))}

    def h_dlq_get(self, ctx):
        d = self.e.get_dlq(ctx["args"]["id"])
        d["related_events"] = [_detail(e) for e in d["related_events"]]
        return 200, d

    def h_redrive(self, ctx):
        d = ctx["data"] or {}
        if set(d) - {"ids", "dry_run", "confirm"} or not isinstance(d.get("ids"), list):
            raise ValidationError("ids (list), dry_run, confirm required")
        dry = d.get("dry_run", True)
        if dry is not True and d.get("confirm") is not True:
            raise HttpError(400, "confirm:true required for a real redrive (use dry_run:true to preview)", "confirmation_required")
        return 200, self.e.redrive(d["ids"], self.actor(ctx), dry_run=dry is True, confirm=d.get("confirm") is True)

    def h_eval(self, ctx):
        r = self.obs.evaluate()
        return 200, {"events": r["events"]}

    def h_events(self, ctx):
        q = ctx["query"]
        sql, p = "SELECT * FROM events WHERE 1=1", []
        if q.get("q"):
            sql += " AND (type LIKE ? OR entity_id LIKE ? OR run_id LIKE ? OR correlation_id LIKE ?)"; p += [f"%{q['q']}%"] * 4
        if q.get("entity_type"):
            sql += " AND entity_type=?"; p.append(q["entity_type"])
        return 200, {"items": [_detail(e) for e in self.s.q(sql + " ORDER BY seq DESC LIMIT 200", p)]}

    def h_integrations(self, ctx):
        return 200, {"items": integration_statuses(self.gov, self.env, self.auth.label), "environment": environment_label(self.env)}

    def h_int_test(self, ctx):
        return 200, test_connection(ctx["args"]["name"], self.env, self.clients, self.http)

    def h_tick(self, ctx):
        return 200, self.e.tick()

    def h_recovery(self, ctx):
        d = ctx["data"] or {}
        if d.get("dry_run", True) is True:
            return 200, {"dry_run": True, "stuck_runs": [r["id"] for r in self.e.stuck_runs()],
                         "stale_sending": [n["id"] for n in self.s.q("SELECT id FROM notifications WHERE status='SENDING'")]}
        if d.get("confirm") is not True:
            raise HttpError(400, "confirm:true required", "confirmation_required")
        self.e.audit(self.actor(ctx), "recovery.run", "system", "recovery")
        return 200, {"recovered": self.e.recover(), "reconciled_notifications": self.e.reconcile_stale_sending()}


def build_app(env=None, db_path=None, clock=None, auth=None, clients=None, http=None, backoff=None, sns_client=None, wa_http=None, gov=None):
    env = dict(os.environ if env is None else env)
    clock = clock or Clock()
    cfg = Config.from_env(env)
    db_path = db_path or env.get("AEGIS_DB_PATH", ".local/aegisnova.db")
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = Store(db_path, clock)
    gov = gov or select_provider(env)
    providers = [LocalSink(), Simulated(), SnsProvider(env, sns_client), WhatsAppCloudProvider(env, wa_http)]
    engine = Engine(store, clock, cfg, gov, providers, backoff=backoff or Backoff())
    obs = Observability(engine, env)
    if auth is None:
        mode = env.get("AEGIS_AUTH_MODE", "dev").lower()
        auth = DevTokenAuth(env.get("AEGIS_DEV_TOKEN_FILE", ".local/dev-tokens.json"), env_token=env.get("AEGIS_INTERNAL_TOKEN")) if mode == "dev" else UnconfiguredExternalAuth()
    return App(store, engine, obs, env, auth, gov, providers, clients, http)
