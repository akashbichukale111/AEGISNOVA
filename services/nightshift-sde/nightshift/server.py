"""HTTP API + static console (stdlib only). JSON in/out, bearer-token auth, consistent error envelope, correlation IDs,
body-size limits, rate limiting, strict security headers. The console (ui/) is plain ES modules — no build step."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import PERMISSIONS
from .errors import (Forbidden, NightShiftError, NotFound, PayloadTooLarge, RateLimited, Unauthorized, ValidationError)
from .redact import REDACTOR
from .service import App, Principal
from .util import iso, new_correlation_id, valid_correlation_id

log = logging.getLogger("nightshift.http")
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; "
       "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

ROUTES: list = []


def route(method: str, pattern: str, *, auth: bool = True):
    rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[A-Za-z0-9_.:-]{1,80})", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn, auth))
        return fn
    return deco


def _int(q: dict, key: str, default: int) -> int:
    try:
        return int(q.get(key, [default])[0])
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be an integer")


def _s(q: dict, key: str) -> str | None:
    v = q.get(key, [None])[0]
    return v[:200] if v else None


class Ctx:
    def __init__(self, app: App, p: Principal | None, q: dict, body, headers, raw: bytes, params: dict):
        self.app, self.p, self.q, self.body, self.headers, self.raw, self.params = app, p, q, body, headers, raw, params


# --------------------------------------------------------------------------------------------- routes
@route("GET", "/api/health", auth=False)
def health(c):  # minimal, no data
    return {"status": "ok", "version": __version__, "time": iso(c.app.clock.now())}


@route("GET", "/api/me")
def me(c):
    return {"actor": c.p.actor, "role": c.p.role, "permissions": sorted(k for k, roles in PERMISSIONS.items() if c.p.role in roles)}


@route("GET", "/api/overview")
def overview(c):
    return c.app.overview(c.p)


@route("GET", "/api/fleet")
def fleet(c):
    return {"items": c.app.fleet(), "generated_at": iso(c.app.clock.now())}


@route("GET", "/api/repos")
def repos(c):
    return {"items": [c.app._repo_view(r) for r in c.app._q("SELECT * FROM repositories WHERE archived_at IS NULL ORDER BY name")]}


@route("POST", "/api/repos")
def repo_create(c):
    return 201, c.app.register_repo(c.p, c.body or {})


@route("GET", "/api/repos/{id}")
def repo_get(c):
    return c.app._repo_view(c.app.store.get_repo(c.params["id"]))


@route("PATCH", "/api/repos/{id}")
def repo_patch(c):
    return c.app.update_repo(c.p, c.params["id"], c.body or {})


@route("DELETE", "/api/repos/{id}")
def repo_delete(c):
    c.app.archive_repo(c.p, c.params["id"])
    return 204, None


@route("POST", "/api/repos/{id}/trigger")
def repo_trigger(c):
    if not c.app.rate_check(f"trigger:{c.p.actor}", c.app.settings.trigger_rate_limit_per_minute):
        raise RateLimited("too many triggers; slow down", code="TRIGGER_RATE_LIMITED")
    body = c.body or {}
    allow = body.get("allow_repair", False)
    if not isinstance(allow, bool):
        raise ValidationError("allow_repair must be a boolean")
    job, created = c.app.trigger(c.p, c.params["id"], allow_repair=allow, idempotency_key=c.headers.get("Idempotency-Key"))
    return (201 if created else 200), {"job": c.app._job_brief(job), "created": created,
                                       "note": None if created else "duplicate trigger suppressed (idempotency key already used)"}


@route("POST", "/api/repos/{id}/check")
def repo_check(c):
    App.need(c.p, "operate")
    return c.app.repo_integration_check(c.app.store.get_repo(c.params["id"]))


@route("GET", "/api/schedules")
def sched_list(c):
    return {"items": c.app.schedules.list(repo_id=_s(c.q, "repo_id"), status=_s(c.q, "status"))}


@route("POST", "/api/schedules/validate")
def sched_validate(c):
    App.need(c.p, "operate")
    body = c.body or {}
    if body.get("allow_repair"):
        App.need(c.p, "authorize_repair")
    return c.app.schedules.validate(body)


@route("POST", "/api/schedules")
def sched_create(c):
    App.need(c.p, "operate")
    body = c.body or {}
    if body.get("allow_repair"):
        App.need(c.p, "authorize_repair")
    return 201, c.app.schedules.create(body, c.p.actor)


@route("GET", "/api/schedules/{id}")
def sched_get(c):
    s = c.app.schedules.get(c.params["id"])
    s["runs"] = c.app.schedules.runs(c.params["id"])
    return s


@route("PATCH", "/api/schedules/{id}")
def sched_patch(c):
    App.need(c.p, "operate")
    body = c.body or {}
    if body.get("allow_repair"):
        App.need(c.p, "authorize_repair")
    return c.app.schedules.update(c.params["id"], body, c.p.actor)


@route("DELETE", "/api/schedules/{id}")
def sched_delete(c):
    App.need(c.p, "operate")
    c.app.schedules.delete(c.params["id"], c.p.actor)
    return 204, None


@route("POST", "/api/schedules/{id}/{action}")
def sched_action(c):
    App.need(c.p, "operate")
    return c.app.schedules.set_status(c.params["id"], c.params["action"], c.p.actor)


@route("POST", "/api/scheduler/tick")
def scheduler_tick(c):
    App.need(c.p, "admin")
    return {"fired": c.app.scheduler.tick()}


@route("POST", "/api/watchdog/tick")
def watchdog_tick(c):
    App.need(c.p, "admin")
    return c.app.watchdog.tick()


@route("GET", "/api/jobs")
def jobs(c):
    q = c.q
    return c.app.list_jobs(repo_id=_s(q, "repo_id"), state=_s(q, "state"), trigger=_s(q, "trigger"), outcome=_s(q, "outcome"), q=_s(q, "q"),
                           schedule_id=_s(q, "schedule_id"), limit=_int(q, "limit", 25), offset=_int(q, "offset", 0))


@route("GET", "/api/jobs/{id}")
def job_get(c):
    return c.app.job_detail(c.params["id"], c.p)


@route("POST", "/api/jobs/{id}/{action}")
def job_action(c):
    body = c.body or {}
    allow = body.get("allow_repair", False)
    if not isinstance(allow, bool):
        raise ValidationError("allow_repair must be a boolean")
    res = c.app.job_action(c.p, c.params["id"], c.params["action"], allow_repair=allow)
    status = 201 if (c.params["action"] == "replay" and res.pop("_created", False)) else 200
    res.pop("_created", None)
    return status, c.app._job_brief(res)


@route("GET", "/api/jobs/{id}/artifacts/{aid}")
def artifact(c):
    a = c.app.artifact(c.params["aid"])
    if a["job_id"] != c.params["id"]:
        raise NotFound("artifact not found", code="ARTIFACT_NOT_FOUND")
    return a


@route("POST", "/api/approvals/{id}/{action}")
def approval_action(c):
    App.need(c.p, "approve")
    body = c.body or {}
    note = str(body.get("note") or body.get("reason") or "")[:500]
    act = c.params["action"]
    if act in ("approve", "reject"):
        return c.app.decide_approval(c.p, c.params["id"], act, note)
    if act == "revoke":
        return c.app.revoke_approval(c.p, c.params["id"], note)
    raise ValidationError("action must be approve, reject or revoke", code="INVALID_ACTION")


@route("GET", "/api/findings")
def findings(c):
    q = c.q
    return c.app.list_findings(repo_id=_s(q, "repo_id"), severity=_s(q, "severity"), status=_s(q, "status"), ecosystem=_s(q, "ecosystem"),
                               q=_s(q, "q"), limit=_int(q, "limit", 25), offset=_int(q, "offset", 0))


@route("GET", "/api/findings/{id}")
def finding(c):
    return c.app.finding_detail(c.params["id"])


@route("GET", "/api/recovery")
def recovery(c):
    return c.app.recovery()


@route("GET", "/api/audit")
def audit(c):
    q = c.q
    return c.app.audit(repo_id=_s(q, "repo_id"), job_id=_s(q, "job_id"), type_prefix=_s(q, "type"), actor=_s(q, "actor"), since=_s(q, "since"),
                       until=_s(q, "until"), state=_s(q, "state"), limit=_int(q, "limit", 50), offset=_int(q, "offset", 0))


@route("GET", "/api/audit/extras")
def audit_extras(c):
    return c.app.audit_extras()


@route("GET", "/api/settings")
def settings(c):
    return c.app.settings_view(c.p)


@route("POST", "/api/providers/{id}/check")
def provider_check(c):
    return c.app.check_provider(c.p, c.params["id"])


@route("GET", "/api/metrics")
def metrics(c):
    return c.app.metrics()


@route("POST", "/api/webhooks/github", auth=False)
def webhook(c):
    if not c.app.rate_check("webhook", c.app.settings.trigger_rate_limit_per_minute * 3):
        raise RateLimited("too many webhook deliveries", code="WEBHOOK_RATE_LIMITED")
    res = c.app.handle_webhook(c.raw, c.headers)
    return (200 if res.get("duplicate") or not res.get("accepted") else 202), res


# --------------------------------------------------------------------------------------------- handler
def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "NightShiftSDE/" + __version__
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # never log query strings (could carry tokens) or headers
            log.info("%s %s", self.address_string(), REDACTOR.text(fmt % args).split("?")[0])

        # -- plumbing
        def _send(self, status: int, payload, corr: str, extra_headers: dict | None = None, *, content_type="application/json; charset=utf-8"):
            if payload is None:
                body = b""
            elif isinstance(payload, (bytes, bytearray)):
                body = bytes(payload)
            else:
                body = json.dumps(REDACTOR.obj(payload), default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Correlation-ID", corr)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "no-cache")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _discard(self, n: int) -> None:
            """Read and drop up to n request-body bytes so the client can read our error response."""
            left = n
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)

        def _error(self, e: Exception, corr: str):
            if isinstance(e, NightShiftError):
                status, code, msg, details = e.http_status, e.code, e.message, e.details
            else:
                log.exception("unhandled error corr=%s", corr)
                status, code, msg, details = 500, "INTERNAL_ERROR", "internal error (see server log with the correlation id)", None
            hdr = {"Retry-After": "30"} if status == 429 else None
            self._send(status, {"error": {"code": code, "message": msg, "details": details, "correlation_id": corr}}, corr, hdr)

        def _static(self, path: str, corr: str):
            rel = "index.html" if path in ("/", "") else path.removeprefix("/ui/").lstrip("/")
            if path not in ("/", "") and not path.startswith("/ui/"):
                return self._error(NotFound("not found"), corr)
            target = (UI_DIR / rel).resolve()
            if UI_DIR.resolve() not in target.parents or not target.is_file():
                return self._error(NotFound("not found"), corr)
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if target.suffix == ".js":
                ctype = "text/javascript"
            self._send(200, target.read_bytes(), corr, content_type=ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

        def _handle(self):
            incoming = self.headers.get("X-Correlation-ID")
            corr = incoming if valid_correlation_id(incoming) else new_correlation_id()
            try:
                url = urlparse(self.path)
                path = url.path.rstrip("/") or "/"
                if not path.startswith("/api/"):
                    if self.command not in ("GET", "HEAD"):
                        raise NotFound("not found")
                    return self._static(path, corr)
                q = parse_qs(url.query, keep_blank_values=False)
                match = None
                path_exists = False
                for method, rx, fn, needs_auth in ROUTES:
                    m = rx.match(path)
                    if m:
                        path_exists = True
                        if method == self.command:
                            match = (fn, needs_auth, m.groupdict())
                            break
                if not match:
                    if path_exists:
                        return self._send(405, {"error": {"code": "METHOD_NOT_ALLOWED", "message": "method not allowed", "details": None, "correlation_id": corr}}, corr)
                    raise NotFound("unknown endpoint", code="ENDPOINT_NOT_FOUND")
                fn, needs_auth, params = match
                # Always consume (or refuse and close) the request body BEFORE any early error response, otherwise unread bytes
                # would be parsed as the next request on a keep-alive connection.
                raw, body = b"", None
                if self.command in ("POST", "PATCH", "PUT"):
                    if self.headers.get("Transfer-Encoding"):
                        self.close_connection = True
                        raise ValidationError("chunked request bodies are not supported; send Content-Length", code="UNSUPPORTED_ENCODING")
                    try:
                        length = int(self.headers.get("Content-Length") or 0)
                    except ValueError:
                        self.close_connection = True
                        raise ValidationError("invalid Content-Length", code="INVALID_CONTENT_LENGTH")
                    if length < 0:
                        self.close_connection = True
                        raise ValidationError("invalid Content-Length", code="INVALID_CONTENT_LENGTH")
                    if length > app.settings.max_body_bytes:
                        self._discard(min(length, app.settings.max_body_bytes * 4))
                        self.close_connection = True
                        raise PayloadTooLarge(f"body exceeds {app.settings.max_body_bytes} bytes")
                    raw = self.rfile.read(length) if length else b""
                p = None
                if needs_auth:
                    auth = self.headers.get("Authorization", "")
                    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
                    p = app.authenticate(token)
                    if p is None:
                        app.store.incr("auth_failures")
                        raise Unauthorized("a valid bearer token is required")
                key = f"api:{p.actor if p else self.client_address[0]}"
                if not app.rate_check(key, app.settings.rate_limit_per_minute):
                    raise RateLimited("rate limit exceeded", code="RATE_LIMITED")
                if raw and "webhooks" not in path:
                    if "json" not in (self.headers.get("Content-Type") or ""):
                        raise ValidationError("Content-Type must be application/json", code="UNSUPPORTED_MEDIA_TYPE")
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        raise ValidationError("request body is not valid JSON", code="INVALID_JSON")
                    if not isinstance(body, dict):
                        raise ValidationError("request body must be a JSON object", code="INVALID_JSON")
                ctx = Ctx(app, p, q, body, self.headers, raw, params)
                if needs_auth:
                    App.need(p, "read")
                res = fn(ctx)
                status = 200
                if isinstance(res, tuple):
                    status, res = res
                self._send(status, res, corr)
            except Exception as e:  # noqa: BLE001
                self._error(e, corr)
            finally:
                app.db.close()  # release this request thread's connection

        do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = do_HEAD = _handle

    return Handler


def create_server(app: App, host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host or app.settings.host, app.settings.port if port is None else port), make_handler(app))
    srv.daemon_threads = True
    return srv
