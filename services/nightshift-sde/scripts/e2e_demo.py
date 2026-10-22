#!/usr/bin/env python3
"""End-to-end demonstration against a RUNNING local server (python -m nightshift serve) with seeded demo repositories.

It only calls the public HTTP API, using the local dev tokens file (never printed). Everything it shows is real execution:
  1. read-only inspection of a repo with vulnerable dependencies            -> investigation_only (no repair claimed)
  2. write-capable run: operator triggers, approver approves (separation of duties) -> sandboxed patch + tests + verifier
  3. a path that is correctly BLOCKED (conflicting evidence / ineligible repo)

usage: NIGHTSHIFT_DATA_DIR=... python scripts/e2e_demo.py [--base http://127.0.0.1:8787]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def tokens() -> dict:
    d = Path(os.environ.get("NIGHTSHIFT_DATA_DIR", "./data")).expanduser().resolve()
    f = Path(os.environ.get("NIGHTSHIFT_TOKENS_FILE", d / "local-tokens.json"))
    return {k: v["token"] for k, v in json.loads(f.read_text()).items()}


def call(base, tok, method, path, body=None, headers=None):
    req = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait(base, tok, jid, states, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        _, d = call(base, tok, "GET", f"/api/jobs/{jid}")
        if d["job"]["state"] in states:
            return d
        time.sleep(0.5)
    raise SystemExit(f"timeout waiting for {jid} to reach {states}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    a = ap.parse_args()
    t = tokens()
    base = a.base
    s, repos = call(base, t["viewer"], "GET", "/api/repos")
    by = {r["slug"]: r for r in repos["items"]}
    if "demo/payments-service" not in by:
        print("demo repositories not found: run `python -m nightshift seed-demo` first")
        return 2
    final = ("COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "DEAD_LETTER", "CANCELLED", "EXPIRED")

    print("== 1. read-only inspection: demo/legacy-batch")
    s, r = call(base, t["operator"], "POST", f"/api/repos/{by['demo/legacy-batch']['id']}/trigger", {"allow_repair": False}, {"Idempotency-Key": "demo-" + uuid.uuid4().hex[:12]})
    d = wait(base, t["viewer"], r["job"]["id"], final)
    print("   state:", d["job"]["state"], "| outcome:", d["job"]["outcome"], "| findings:", len(d["findings"]))
    print("   ", d["explanation"]["summary"])

    print("== idempotency: the same Idempotency-Key must not create a second job")
    key = "demo-" + uuid.uuid4().hex[:12]
    _, a1 = call(base, t["operator"], "POST", f"/api/repos/{by['demo/legacy-batch']['id']}/trigger", {}, {"Idempotency-Key": key})
    _, a2 = call(base, t["operator"], "POST", f"/api/repos/{by['demo/legacy-batch']['id']}/trigger", {}, {"Idempotency-Key": key})
    print("   same job:", a1["job"]["id"] == a2["job"]["id"], "| second call created:", a2["created"])

    print("== 2. write-capable run: demo/payments-service (admin requests, a different approver approves)")
    s, r = call(base, t["admin"], "POST", f"/api/repos/{by['demo/payments-service']['id']}/trigger", {"allow_repair": True}, {"Idempotency-Key": "demo-" + uuid.uuid4().hex[:12]})
    if s >= 400:
        print("   trigger refused:", r)
        return 1
    jid = r["job"]["id"]
    d = wait(base, t["viewer"], jid, final + ("WAITING_FOR_APPROVAL",))
    print("   state:", d["job"]["state"])
    if d["job"]["state"] == "WAITING_FOR_APPROVAL":
        appr = next(x for x in d["approvals"] if x["status"] == "pending")
        print("   scoped approval requested:", appr["id"], "scope keys:", sorted(appr["scope"]))
        s, own = call(base, t["admin"], "POST", f"/api/approvals/{appr['id']}/approve", {"note": "self-approval attempt"})
        print("   requester self-approval (must be refused) ->", s, own.get("error", {}).get("code"))
        s, ok = call(base, t["approver"], "POST", f"/api/approvals/{appr['id']}/approve", {"note": "demo approval by a different principal"})
        print("   independent approver ->", s)
        d = wait(base, t["viewer"], jid, final)
    print("   final state:", d["job"]["state"], "| outcome:", d["job"]["outcome"])
    for art in d["artifacts"]:
        print("   artifact:", art["kind"], art["name"], art["sha256"][:12])
    print("   ", d["explanation"]["summary"])

    print("== 3. blocked path: demo/conflict-lab (conflicting evidence must stop automated repair)")
    s, r = call(base, t["admin"], "POST", f"/api/repos/{by['demo/conflict-lab']['id']}/trigger", {"allow_repair": True}, {"Idempotency-Key": "demo-" + uuid.uuid4().hex[:12]})
    d = wait(base, t["viewer"], r["job"]["id"], final + ("WAITING_FOR_APPROVAL",))
    print("   state:", d["job"]["state"], "| outcome:", d["job"]["outcome"])
    print("   ", d["explanation"]["summary"])
    s, v = call(base, t["viewer"], "GET", "/api/audit?limit=1")
    print("== audit hash chain:", v["chain"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
