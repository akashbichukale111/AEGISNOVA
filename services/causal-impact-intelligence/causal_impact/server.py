"""Local stdlib HTTP API (v1) + static UI. Binds to 127.0.0.1 only. In-memory session; no external calls."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from . import SCHEMA_VERSION, __version__, parsers, analysis, report
from .parsers import InputError

STATE = {"graph": None, "incident": None, "kinds": [], "last": None}
STATIC = os.path.join(os.path.dirname(__file__), "static")
FIX = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")
MAX_BODY = 4_000_000


def _need_graph():
    if STATE["graph"] is None: raise InputError("NO_GRAPH", "import a graph first (POST /api/v1/import or /api/v1/demo)")
    return STATE["graph"]


def _need_inc(b=None):
    inc = parsers.parse_incident(b["incident"]) if b and b.get("incident") else STATE["incident"]
    if inc is None: raise InputError("NO_INCIDENT", "no incident supplied")
    return inc


def load(files, incident=None):
    g, kinds = parsers.build(files)
    STATE.update(graph=g, kinds=kinds, incident=parsers.parse_incident(incident) if incident else None, last=None)
    return {"status": "OK", "formats": kinds, "validation": g.validate(), "coverage": g.coverage(), "graph_hash": g.hash()}


def load_demo():
    def rd(n):
        with open(os.path.join(FIX, n), encoding="utf-8") as f: return f.read()
    r = load([{"name": "demo_service_map.json", "content": rd("demo_service_map.json")}], rd("demo_incident.json"))
    r["label"] = "DEMO FIXTURE - illustrative data, not facts about any real system"; return r


def handle(method, path, body):
    """Pure router: returns (status, payload). Used by HTTP handler and tests."""
    try:
        p = [unquote(x) for x in path.strip("/").split("/")]
        if p[:2] != ["api", "v1"]: return 404, {"error": "NOT_FOUND"}
        r = p[2:]
        if method == "GET" and r == ["health"]:
            return 200, {"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION, "graph_loaded": STATE["graph"] is not None,
                         "supported_formats": ["package.json", "package-lock.json", "requirements.txt", "pyproject.toml", "service-map.json"],
                         "optional_llm_provider": "not configured (not required)"}
        if method == "POST" and r == ["demo"]: return 200, load_demo()
        if method == "POST" and r == ["import"]:
            return 200, load(body.get("files") or [], body.get("incident"))
        if method == "POST" and r == ["incident"]:
            STATE["incident"] = parsers.parse_incident(body["incident"] if "incident" in body else body); return 200, {"status": "OK", "incident": STATE["incident"]}
        if method == "GET" and r == ["graph"]: return 200, {**_need_graph().to_dict(), "validation": _need_graph().validate(), "incident": STATE["incident"]}
        if method == "GET" and r[:1] == ["node"] and len(r) == 2:
            g = _need_graph()
            if r[1] not in g.nodes: return 404, {"error": "NODE_NOT_FOUND", "message": r[1]}
            up, _ = g.upstream(r[1], 3); dn, _ = g.downstream(r[1], 3)
            fmt = lambda info: [{"node_id": k, "depth": v["depth"], "path": [analysis._brief(e) for e in v["path"]]} for k, v in info.items() if k != r[1]]
            return 200, {"node": g.nodes[r[1]], "upstream": fmt(up), "downstream": fmt(dn)}
        if method == "POST" and r == ["rca"]:
            return 200, analysis.root_cause(_need_graph(), _need_inc(body))
        if method == "POST" and r == ["impact"]:
            g = _need_graph(); imp = analysis.impact(g, body.get("node_id", ""), int(body.get("max_depth", 6)), int(body.get("max_nodes", 500)),
                                                     body.get("environment"), body.get("node_types"), body.get("edge_types"), bool(body.get("exclude_dev")))
            return 200, {"impact": imp, "blast_radius": analysis.blast_radius(g, imp)}
        if method == "POST" and r == ["analyze"]:
            STATE["last"] = analysis.analyze(_need_graph(), _need_inc(body), body.get("node_id")); return 200, STATE["last"]
        if method == "POST" and r in (["counterfactual"], ["compare"]):
            return 200, analysis.counterfactual(_need_graph(), _need_inc(body), body.get("scenario") or {})
        if method == "POST" and r == ["export"]:
            a = STATE["last"] or analysis.analyze(_need_graph(), _need_inc(body)); STATE["last"] = a
            return 200, {"format": body.get("format", "json"), "content": report.to_markdown(a) if body.get("format") == "markdown" else report.to_json(a)}
        return 404, {"error": "NOT_FOUND"}
    except InputError as e: return 400, {"error": e.code, "message": str(e)}
    except (ValueError, TypeError, KeyError) as e: return 400, {"error": "BAD_REQUEST", "message": f"{type(e).__name__}: {e}"}
    except Exception as e: return 500, {"error": "INTERNAL", "message": type(e).__name__}


class H(BaseHTTPRequestHandler):
    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f: return self._send(200, f.read(), "text/html; charset=utf-8")
        self._send(*handle("GET", path, {}))

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_BODY: return self._send(413, {"error": "INPUT_TOO_LARGE"})
        try: body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError: return self._send(400, {"error": "MALFORMED_JSON"})
        self._send(*handle("POST", urlparse(self.path).path, body))

    def log_message(self, *a): pass


def serve(port=8765):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"AEGISNOVA Causal Impact Intelligence on http://127.0.0.1:{port}  (Ctrl+C to stop)"); srv.serve_forever()
