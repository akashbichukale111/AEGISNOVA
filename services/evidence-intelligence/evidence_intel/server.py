"""HTTP API + static UI (stdlib). Run: python -m evidence_intel.server"""
import json, mimetypes, os, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .core import Service, ValidationError, redact
from .fixtures import FixtureHTTP, DEMO_ENV

STATIC = Path(__file__).parent / "static"
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'"
R = lambda p: re.compile("^/api/v1/" + p + "$")
ROUTES = [("POST", R("research"), "create"), ("GET", R(r"research/([\w-]+)"), "get"), ("POST", R(r"research/([\w-]+)/refresh"), "refresh"),
          ("GET", R(r"research/([\w-]+)/diff"), "diff"), ("GET", R(r"research/([\w-]+)/export"), "export"), ("GET", R(r"evidence/([\w-]+)"), "evidence"),
          ("GET", R("providers/health"), "health"), ("GET", R("settings"), "settings")]

def make_handler(svc):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, code, body, ctype="application/json", extra=None):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Security-Policy", CSP); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(raw)
        def _handle(self, method):
            path = self.path.split("?")[0]
            if method == "GET" and path in ("/health", "/ready"): return self._send(200, {"status": "ok"})
            if method == "GET" and not path.startswith("/api/"):
                name = "index.html" if path == "/" else path.lstrip("/")
                f = (STATIC / name).resolve()
                if STATIC.resolve() in f.parents and f.is_file(): return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                return self._send(404, {"error": "not found"})
            for m, rx, fn in ROUTES:
                mt = rx.match(path)
                if m == method and mt:
                    try:
                        if fn == "create":
                            n = int(self.headers.get("Content-Length") or 0)
                            if n > 65536: return self._send(413, {"error": "body too large"})
                            try: body = json.loads(self.rfile.read(n) or b"{}")
                            except ValueError: return self._send(400, {"errors": ["invalid JSON"]})
                            return self._send(201, svc.research(body))
                        res = getattr(svc, fn)(*mt.groups())
                        return self._send(200, res, extra={"Content-Disposition": "attachment; filename=evidence-export.json"} if fn == "export" else None)
                    except ValidationError as e: return self._send(400, {"errors": e.args[0]})
                    except KeyError: return self._send(404, {"error": "not found"})
                    except Exception as e: return self._send(500, {"error": redact(f"{type(e).__name__}")})
            self._send(404, {"error": "not found"})
        def do_GET(self): self._handle("GET")
        def do_POST(self): self._handle("POST")
    return H

def build_service():
    demo = os.environ.get("EI_MODE", "live").lower() == "demo"
    cfg = {k: int(os.environ[v]) for k, v in (("fresh_hours", "EI_FRESH_HOURS"), ("aging_hours", "EI_AGING_HOURS"), ("stale_hours", "EI_STALE_HOURS"), ("timeout", "EI_TIMEOUT_SECONDS")) if os.environ.get(v)}
    env = DEMO_ENV if demo else {k: os.environ[k] for k in ("TAVILY_API_KEY", "GITHUB_TOKEN") if os.environ.get(k)}
    kw = {"http": FixtureHTTP()} if demo else {}
    return Service(db=os.environ.get("EI_DB", "evidence.db"), env=env, cfg=cfg, demo=demo, **kw)

def serve(svc, host="127.0.0.1", port=8080):
    srv = ThreadingHTTPServer((host, port), make_handler(svc)); return srv

if __name__ == "__main__":
    port = int(os.environ.get("EI_PORT", "8080")); s = serve(build_service(), port=port)
    print(f"Evidence Intelligence on http://127.0.0.1:{port} (mode={'demo' if os.environ.get('EI_MODE','').lower()=='demo' else 'live'})"); s.serve_forever()
