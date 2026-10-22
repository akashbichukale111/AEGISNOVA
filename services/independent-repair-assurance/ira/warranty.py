import datetime as dt, json, os, re, shutil, tempfile, uuid
from . import core
def _p(d, wid):
    if not re.fullmatch(r"war_[0-9a-f]{12}", wid or ""): raise core.PatchError("BAD_ID", str(wid))
    return os.path.join(d, "warranties", wid + ".json")
def save(d, w): os.makedirs(os.path.join(d, "warranties"), exist_ok=True); json.dump(w, open(_p(d, w["warranty_id"]), "w"), indent=1)
def load(d, wid):
    p = _p(d, wid)
    if not os.path.exists(p): raise core.PatchError("NOT_FOUND", wid)
    return json.load(open(p))
def create(R, root, changes, days, d):
    n = dt.datetime.now(dt.timezone.utc); p = R["proof"]
    w = {"warranty_id": "war_" + uuid.uuid4().hex[:12], "proof_id": p["proof_id"], "run_id": R["run_id"], "repo_id": p["repo_id"], "base_sha": p["base_sha"], "patch_hash": p["patch_hash"],
         "covered_files": {k: (core.sha(v) if v is not None else None) for k, v in changes.items()}, "claims": p["claim"], "tests": [c["command"] for c in p["commands_executed"]],
         "start": n.isoformat(), "expires": (n + dt.timedelta(days=days)).isoformat(), "last_revalidated": n.isoformat(), "state": "ACTIVE", "previous_state": None, "pending_triggers": [],
         "history": [{"at": n.isoformat(), "from": None, "to": "ACTIVE", "reason": "initial verification: " + R["status"]}], "next_recommended_check": (n + dt.timedelta(days=days / 2)).isoformat(),
         "disclaimer": "Time-bounded assurance/revalidation commitment, not a legal guarantee; says nothing about future safety. Evaluate against the repo WITH the repair applied."}
    snap = os.path.join(d, 'snapshots', w['warranty_id']); os.makedirs(os.path.dirname(snap), exist_ok=True); core.materialize(root, snap, changes)
    save(d, w); return w
def snapshot_dir(d, wid): _p(d, wid); return os.path.join(d, 'snapshots', wid)
def evaluate(w, current_dir=None, patch_hash=None, add_triggers=(), when=None):
    n = when or dt.datetime.now(dt.timezone.utc); old = w["state"]; why = []
    w["pending_triggers"] = sorted(set(w["pending_triggers"]) | set(add_triggers))
    if old in ("SUSPENDED", "INVALIDATED"): new = old; why.append("sticky state: " + old)
    else:
        new = "ACTIVE"
        if patch_hash and patch_hash != w["patch_hash"]: new = "INVALIDATED"; why.append("patch hash differs from proven artifact")
        elif current_dir is not None and not os.path.isdir(current_dir): new = "SOURCE_UNAVAILABLE"; why.append("source directory unavailable")
        elif current_dir is not None:
            def h(p):
                fp = os.path.join(current_dir, p); return core.sha(open(fp, "rb").read()) if os.path.isfile(fp) else None
            ch = [p for p, x in w["covered_files"].items() if h(p) != x]
            if ch: new = "INVALIDATED"; why.append("covered file changed: " + ", ".join(ch))
        if new == "ACTIVE":
            exp, lr, start = (dt.datetime.fromisoformat(w[k]) for k in ("expires", "last_revalidated", "start"))
            if n >= exp: new = "EXPIRED"; why.append("warranty window elapsed")
            elif w["pending_triggers"]: new = "REQUIRES_REVALIDATION"; why.append("triggers: " + ", ".join(w["pending_triggers"]))
            elif (n - lr) > (exp - start) / 2: new = "AGING"; why.append("last revalidation older than half the window")
            else: why.append("evidence fresh, covered files unchanged")
    if new != old:
        w["previous_state"] = old; w["state"] = new; w["history"].append({"at": n.isoformat(), "from": old, "to": new, "reason": "; ".join(why)})
    w["last_evaluated"] = n.isoformat(); w["last_reason"] = "; ".join(why); return w
def revalidate(w, current_dir, d, when=None):
    """Manual revalidation hook (a scheduler may call this). Re-runs allowlisted tests on a temp copy; original proof is preserved."""
    n = when or dt.datetime.now(dt.timezone.utc)
    if not os.path.isdir(current_dir): w = evaluate(w, current_dir, when=n); save(d, w); return w
    tmp = tempfile.mkdtemp(prefix="ira_rv_", dir=os.environ.get("IRA_TMP_ROOT") or None)
    try: dest = os.path.join(tmp, "src"); core.materialize(current_dir, dest); r = core.run_cmd(core.TEST_CMD, dest)
    finally: shutil.rmtree(tmp, ignore_errors=True)
    w["history"].append({"at": n.isoformat(), "from": w["state"], "to": w["state"], "event": "REVALIDATION_RUN", "reason": f"revalidation run: {r['status']} {r.get('reason') or ''}".strip()})
    if r["status"] == "PASSED": w["last_revalidated"] = n.isoformat(); w["pending_triggers"] = []
    elif r["status"] in ("FAILED", "INCONCLUSIVE"): w["pending_triggers"] = sorted(set(w["pending_triggers"]) | {"failed_recheck"})
    w = evaluate(w, current_dir, when=n); save(d, w)
    w["revalidation"] = {"status": r["status"], "reason": r.get("reason"), "proof_preserved": w["proof_id"]}; return w
