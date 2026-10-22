"""Run: python -m aegisnova_ops  (local dev server + background worker)."""
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .app import build_app, MAX_BODY


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        server_version = "AegisOps"
        sys_version = ""

        def _do(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                body = b"x" * (MAX_BODY + 1)   # trigger 413 without reading the stream
            else:
                body = self.rfile.read(n) if n else b""
            status, headers, out = app.handle(self.command, self.path, dict(self.headers.items()), body)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = do_OPTIONS = _do

        def log_message(self, fmt, *args):   # never log bodies/headers/query strings
            sys.stderr.write("%s %s -> %s\n" % (self.command, self.path.split("?")[0], args[1] if len(args) > 1 else ""))
    return H


def main():
    env = dict(os.environ)
    host, port = env.get("AEGIS_HOST", "127.0.0.1"), int(env.get("AEGIS_PORT", "8080"))
    if host not in ("127.0.0.1", "localhost", "::1") and env.get("AEGIS_ALLOW_NONLOCAL_BIND") != "true":
        sys.exit("Refusing to bind a non-loopback address (dev auth is NON-PRODUCTION). Set AEGIS_ALLOW_NONLOCAL_BIND=true to override.")
    app = build_app(env)
    app.e.recover()
    stop = threading.Event()
    if env.get("AEGIS_WORKER", "on") != "off":
        def loop():
            n = 0
            while not stop.is_set():
                try:
                    app.e.tick()
                    n += 1
                    if n % 5 == 0:
                        app.obs.evaluate()
                    if n % 600 == 0:
                        app.e.purge_expired()
                except Exception as e:
                    app.e._event("worker", app.e.worker_id, "worker.error", detail={"error": type(e).__name__})
                stop.wait(app.e.cfg.worker_interval_s)
        threading.Thread(target=loop, daemon=True, name="worker").start()
    srv = ThreadingHTTPServer((host, port), make_handler(app))

    def shutdown(*_):
        stop.set()
        threading.Thread(target=srv.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print(f"AEGISNOVA Ops listening on http://{host}:{port}  [{app.auth.label}]")
    print("Dev tokens (never commit): ./.local/dev-tokens.json")
    srv.serve_forever()
    srv.server_close()
    app.s.close()
    print("shut down cleanly")


if __name__ == "__main__":
    main()
