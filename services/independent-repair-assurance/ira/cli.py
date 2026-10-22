import argparse, json, os, sys
from . import core, warranty
HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS = os.environ.get("IRA_REPO_ROOT", os.path.join(HOME, "fixtures", "repos")); DATA = os.environ.get("IRA_DATA_DIR", os.path.join(HOME, ".data"))
def health():
    return {"version": core.SCHEMA_VERSION, "offline_ok": True, "runtime_execution_enabled": core.exec_enabled(), "sandbox": {"type": "process-level (not container)", "network_isolation": core.net_isolation(), "container_runtime": False},
            "allowed_commands": core.ALLOWED_CMDS, "limits": core.LIMITS, "warrant_key_configured": bool(os.environ.get("IRA_WARRANT_KEY")), "proof_hmac_configured": bool(os.environ.get("IRA_PROOF_HMAC_KEY")),
            "tools": {"python": sys.version.split()[0], "linter": "NOT_AVAILABLE"}, "repos": sorted(os.listdir(REPOS)) if os.path.isdir(REPOS) else []}
def main(argv=None):
    ap = argparse.ArgumentParser(prog="ira"); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--repo", default="sample"); r.add_argument("--patch", required=True); r.add_argument("--base-sha", default="auto"); r.add_argument("--claim", default="")
    r.add_argument("--claim-tests-passed", action="store_true"); r.add_argument("--warrant-file"); r.add_argument("--demo-warrant", action="store_true"); r.add_argument("--allow-exec", action="store_true")
    for n in ("report", "breaker", "risk", "proof", "proof-report"): sp.add_parser(n).add_argument("run_id")
    w = sp.add_parser("warrant-check"); w.add_argument("run_id"); wa = sp.add_parser("warranty"); wa.add_argument("action", choices=["check", "revalidate"]); wa.add_argument("warranty_id"); wa.add_argument("--repo-dir"); wa.add_argument("--trigger", action="append", default=[])
    sp.add_parser("health"); sp.add_parser("serve").add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "health": out = health()
        elif a.cmd == "serve":
            from .server import serve; serve(a.port); return 0
        elif a.cmd == "run":
            if a.allow_exec: os.environ["IRA_ALLOW_LOCAL_EXEC"] = "1"
            base = core.tree_hash(core.resolve_repo(REPOS, a.repo)) if a.base_sha == "auto" else a.base_sha
            req = {"repo": a.repo, "base_sha": base, "patch": open(a.patch).read(), "claim": {"summary": a.claim, "tests_passed": a.claim_tests_passed or None}, "demo_warrant": a.demo_warrant}
            if a.warrant_file: req["warrant"] = json.load(open(a.warrant_file))
            R = core.assess(req, DATA, REPOS); out = {"run_id": R["run_id"], "status": R["status"], "reason": R["reason"], "stages": [(s["stage"], s["status"]) for s in R["stages"]], "proof_hash": R["proof"]["proof_hash"], "risk": R["risk"]["overall"], "warranty_id": R["warranty_id"]}
        elif a.cmd in ("report", "breaker", "risk", "proof", "proof-report", "warrant-check"):
            R = core.load_run(DATA, a.run_id)
            if a.cmd == "proof-report": print(core.render_report(R)); return 0
            out = {"report": {k: R[k] for k in ("run_id", "status", "reason", "identity", "stages", "tests", "audit", "limitations")}, "breaker": R["breaker"], "risk": R["risk"], "proof": core.export_proof(R), "warrant-check": R["warrant"]}[a.cmd]
        else:
            wr = warranty.load(DATA, a.warranty_id)
            if a.action == "check": wr = warranty.evaluate(wr, a.repo_dir, add_triggers=a.trigger); warranty.save(DATA, wr)
            else: wr = warranty.revalidate(wr, a.repo_dir, DATA)
            out = wr
        print(json.dumps(out, indent=2)); return 0
    except core.PatchError as e:
        print(json.dumps({"error": {"code": e.code, "message": e.msg}})); return 2
if __name__ == "__main__": sys.exit(main())
