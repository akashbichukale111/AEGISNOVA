import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from aegisnova_ops.app import build_app
from aegisnova_ops.auth import FixedTokenAuth
from aegisnova_ops.clock import FakeClock
from aegisnova_ops.engine import Backoff
from aegisnova_ops.governance import LocalDevGovernance

TOKENS = {"viewer": "tok-viewer", "operator": "tok-operator", "admin": "tok-admin"}


def make(env=None, clock=None, db=":memory:", **kw):
    clock = clock or FakeClock()
    app = build_app(env=env if env is not None else {}, db_path=db, clock=clock, auth=FixedTokenAuth(dict(TOKENS)),
                    backoff=Backoff(jitter=0), **kw)
    return app, clock


def call(app, method, path, role="admin", body=None, headers=None, raw=None):
    h = {"host": "localhost", "content-type": "application/json"}
    if role:
        h["authorization"] = "Bearer " + TOKENS[role]
    h.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    status, hd, out = app.handle(method, path, h, data)
    try:
        return status, json.loads(out) if out else None
    except ValueError:
        return status, out.decode()


def start(app, approval=True, **payload):
    payload.setdefault("approval_required", approval)
    run, _ = app.e.start_run({"workflow_type": "sample.governed_action", "payload": payload})
    return run


def grant(app, run_id, decision="granted"):
    ap = app.s.one("SELECT * FROM approvals WHERE run_id=?", (run_id,))
    env = app.gov.issue_decision(ap, decision, app.e.clock.now())
    return app.e.submit_decision(env), env


def status(app, run_id):
    return app.e.get_run(run_id)["status"]


class Base(unittest.TestCase):
    def setUp(self):
        self.app, self.clock = make()
        self.e, self.s = self.app.e, self.app.s

    def tearDown(self):
        if hasattr(self, "s") and self.s:
            try:
                self.s.close()
            except Exception:
                pass
        super().tearDown()
