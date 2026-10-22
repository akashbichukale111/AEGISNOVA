import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import core, warranty, cli
MAXB = 1_000_000
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj, ctype="application/json"):
        b = obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.send_header("X-Content-Type-Options", "nosniff"); self.end_headers(); self.wfile.write(b)
    def err(self, code, c, m): self.send(code, {"error": {"code": c, "message": m}})
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAXB: raise core.PatchError("PAYLOAD_TOO_LARGE", "limit 1MB")
        try: d = json.loads(self.rfile.read(n) or b"{}")
        except Exception: raise core.PatchError("BAD_JSON", "invalid JSON")
        if not isinstance(d, dict): raise core.PatchError("BAD_JSON", "object expected")
        return d
    def route(self, method):
        p = self.path.split("?")[0]
        if method == "GET" and p == "/": return self.send(200, open(os.path.join(cli.HOME, "ui", "index.html")).read(), "text/html; charset=utf-8")
        if method == "GET" and p == "/v1/health": return self.send(200, cli.health())
        if method == "GET" and p == "/v1/repos": return self.send(200, {"repos": [{"name": n, "base_sha": core.tree_hash(os.path.join(cli.REPOS, n)), "label": "DEMO fixture"} for n in sorted(os.listdir(cli.REPOS))]})
        if method == "GET" and p == "/v1/demo":
            d = os.path.join(cli.HOME, "fixtures", "patches"); return self.send(200, {"label": "DEMO fixtures", "patches": {f: open(os.path.join(d, f)).read() for f in sorted(os.listdir(d))}})
        if method == "POST" and p == "/v1/runs":
            q = self.body(); R = core.assess(q, cli.DATA, cli.REPOS); return self.send(201, R)
        m = re.fullmatch(r"/v1/runs/(run_[0-9a-f]{12})(?:/(breaker|risk|proof|proof/report|warrant))?", p)
        if method == "GET" and m:
            R = core.load_run(cli.DATA, m[1]); s = m[2]
            if s == "proof/report": return self.send(200, core.render_report(R), "text/plain; charset=utf-8")
            return self.send(200, {None: R, "breaker": R["breaker"], "risk": R["risk"], "proof": core.export_proof(R), "warrant": R["warrant"]}[s])
        if method == "POST" and p == "/v1/warrants/check":
            q = self.body(); c = q.get("context") or {}
            if not all(k in c for k in ("repo_id", "base_sha", "patch_hash", "paths", "action")): raise core.PatchError("BAD_REQUEST", "context requires repo_id, base_sha, patch_hash, paths, action")
            return self.send(200, core.check_warrant(q.get("warrant"), c))
        m = re.fullmatch(r"/v1/warranty/(war_[0-9a-f]{12})(?:/(revalidate|check))?", p)
        if m and method in ("GET", "POST"):
            w = warranty.load(cli.DATA, m[1]); q = self.body() if method == "POST" else {}
            rd = warranty.snapshot_dir(cli.DATA, m[1]) if q.get("repo") == "@snapshot" else (core.resolve_repo(cli.REPOS, q["repo"]) if q.get("repo") else None)
            if m[2] == "revalidate": w = warranty.revalidate(w, rd, cli.DATA) if rd else warranty.evaluate(w)
            elif method == "POST" or m[2] == "check": w = warranty.evaluate(w, rd, add_triggers=[t for t in q.get("triggers", []) if t in ("base_branch_change", "dependency_advisory", "test_change", "policy_update", "failed_recheck")])
            warranty.save(cli.DATA, w); return self.send(200, w)
        self.err(404, "NOT_FOUND", "no such route")
    def handle_any(self, method):
        try: self.route(method)
        except core.PatchError as e: self.err(404 if e.code == "NOT_FOUND" else 413 if e.code == "PAYLOAD_TOO_LARGE" else 400, e.code, e.msg)
        except Exception: self.err(500, "INTERNAL", "internal error")
    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")
def serve(port=8765):
    s = ThreadingHTTPServer(("127.0.0.1", port), H); print(f"http://127.0.0.1:{port}  (runtime exec enabled: {core.exec_enabled()})", flush=True); s.serve_forever()
