import ast, datetime as dt, fnmatch, hashlib, hmac, json, os, re, resource, shutil, signal, subprocess, sys, tempfile, time, uuid
SCHEMA_VERSION = "1.0"
LIMITS = {"max_patch_bytes": 200000, "max_files": 20, "max_changed_lines": 500}
FORBIDDEN = (".git/", ".env", "aegis.json", ".github/", "id_rsa", ".ssh/")
TEST_CMD = ["python3", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]
ALLOWED_CMDS = [TEST_CMD]
TEST_KEY = b"TEST-ONLY-KEY-NOT-A-SECRET"
SECRET_RE = re.compile(r"(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:password|secret|token|api_key)\s*[=:]\s*['\"][^'\"\s]{8,}['\"])")
UNSAFE_RE = re.compile(r"\b(eval|exec)\(|os\.system\(|shell\s*=\s*True|pickle\.loads\(|verify\s*=\s*False")
STAGES = ["RECEIVED", "IDENTITY_VALIDATION", "STATIC_ANALYSIS", "TEST_PLAN", "TEST_EXECUTION", "INDEPENDENT_AUDIT", "WARRANT_CHECK", "RESIDUAL_RISK", "PROOF_GENERATION"]
LIMITATIONS = ["Process-level isolation only (temp copy, filtered env, rlimits, netns if available); NOT a container/VM sandbox.",
               "Python/unittest ecosystem only; other languages are reported as unsupported/UNKNOWN.",
               "Coverage is not measured; untested paths are unknown.",
               "Patch Breaker is rule-based plus real test results; it cannot prove absence of defects.",
               "No linter/type-checker baseline comparison is performed (NOT_RUN)."]

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
def sha(b): return hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()
def redact(s): return SECRET_RE.sub("[REDACTED]", s)

class PatchError(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"{code}: {msg}"); self.code, self.msg = code, msg

def _p(s):
    s = s.split("\t")[0].strip()
    if s == "/dev/null": return s
    return s[2:] if s.startswith(("a/", "b/")) else s

def check_path(p):
    if "\x00" in p or "\\" in p or p.startswith("/") or re.match(r"^[A-Za-z]:", p): raise PatchError("PATH_ABSOLUTE", p)
    if ".." in p.split("/"): raise PatchError("PATH_TRAVERSAL", p)
    for f in FORBIDDEN:
        if (f.endswith("/") and (p.startswith(f) or ("/" + f) in p)) or (not f.endswith("/") and os.path.basename(p) == f):
            raise PatchError("FORBIDDEN_PATH", p)

def parse_diff(text):
    if len(text.encode()) > LIMITS["max_patch_bytes"]: raise PatchError("PATCH_TOO_LARGE", "bytes")
    if "GIT binary patch" in text or re.search(r"^Binary files ", text, re.M): raise PatchError("BINARY_REJECTED", "binary policy")
    L, i, files, cur = text.split("\n"), 0, [], None
    while i < len(L):
        l = L[i]
        if l.startswith("--- "):
            if i + 1 >= len(L) or not L[i + 1].startswith("+++ "): raise PatchError("MALFORMED", "missing +++ header")
            cur = {"old": _p(l[4:]), "new": _p(L[i + 1][4:]), "hunks": [], "added": 0, "removed": 0}
            for p in (cur["old"], cur["new"]):
                if p != "/dev/null": check_path(p)
            files.append(cur); i += 2; continue
        if l.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", l)
            if not m or cur is None: raise PatchError("MALFORMED", "bad hunk header")
            h = {"os": int(m[1]), "ol": int(m[2]) if m[2] is not None else 1, "ns": int(m[3]), "nl": int(m[4]) if m[4] is not None else 1, "lines": []}
            i += 1; o = n = 0
            while (o < h["ol"] or n < h["nl"]) and i < len(L):
                t = L[i]; c = t[:1] if t else " "
                if c == "\\": i += 1; continue
                if c == " ": o += 1; n += 1
                elif c == "-": o += 1; cur["removed"] += 1
                elif c == "+": n += 1; cur["added"] += 1
                else: raise PatchError("MALFORMED", "bad hunk line")
                h["lines"].append((c, t[1:])); i += 1
            if o != h["ol"] or n != h["nl"]: raise PatchError("MALFORMED", "hunk length mismatch")
            cur["hunks"].append(h); continue
        i += 1
    if not files or any(not f["hunks"] for f in files): raise PatchError("MALFORMED", "no files/hunks")
    if len(files) > LIMITS["max_files"]: raise PatchError("PATCH_TOO_LARGE", "files")
    if sum(f["added"] + f["removed"] for f in files) > LIMITS["max_changed_lines"]: raise PatchError("PATCH_TOO_LARGE", "lines")
    return files

def safe_join(root, rel):
    p = os.path.realpath(os.path.join(root, rel))
    if not p.startswith(os.path.realpath(root) + os.sep): raise PatchError("PATH_TRAVERSAL", rel)
    return p

def fpath(f): return f["new"] if f["new"] != "/dev/null" else f["old"]

def apply_patch(files, root):
    out = {}
    for f in files:
        path = fpath(f)
        if f["old"] == "/dev/null":
            if os.path.exists(safe_join(root, path)): raise PatchError("DOES_NOT_APPLY", "exists: " + path)
            lines, eol = [], True
        else:
            fp = safe_join(root, f["old"])
            if not os.path.isfile(fp): raise PatchError("DOES_NOT_APPLY", "missing: " + f["old"])
            try: txt = open(fp, encoding="utf-8").read()
            except UnicodeDecodeError: raise PatchError("BINARY_REJECTED", f["old"])
            lines = txt.split("\n"); eol = lines[-1] == ""
            if eol: lines.pop()
        off = 0
        for h in f["hunks"]:
            st = (h["os"] - 1 if h["ol"] > 0 else h["os"]) + off
            old = [t for c, t in h["lines"] if c in " -"]; new = [t for c, t in h["lines"] if c in " +"]
            if st < 0 or lines[st:st + len(old)] != old: raise PatchError("DOES_NOT_APPLY", f"context mismatch in {path}")
            lines[st:st + len(old)] = new; off += len(new) - len(old)
        out[path] = None if f["new"] == "/dev/null" else "\n".join(lines) + ("\n" if eol and lines else "")
    return out

def tree_hash(root):
    h = hashlib.sha256()
    for dp, dn, fn in os.walk(root):
        dn[:] = sorted(d for d in dn if d not in ("__pycache__", ".git"))
        for f in sorted(fn):
            if f.endswith(".pyc"): continue
            p = os.path.join(dp, f); h.update(os.path.relpath(p, root).encode() + b"\0" + hashlib.sha256(open(p, "rb").read()).digest())
    return h.hexdigest()

def materialize(root, dest, changes=None):
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns("__pycache__", ".git", "*.pyc"))
    for p, c in (changes or {}).items():
        fp = safe_join(dest, p)
        if c is None:
            if os.path.exists(fp): os.remove(fp)
        else:
            os.makedirs(os.path.dirname(fp), exist_ok=True); open(fp, "w", encoding="utf-8").write(c)

def _ast(src):
    try: return ast.parse(src)
    except SyntaxError: return None

def silent_handlers(src):
    t = _ast(src); n = 0
    for nd in (ast.walk(t) if t else []):
        if isinstance(nd, ast.ExceptHandler):
            broad = nd.type is None or (isinstance(nd.type, ast.Name) and nd.type.id in ("Exception", "BaseException"))
            if broad and not any(isinstance(x, ast.Raise) for x in ast.walk(nd)): n += 1
    return n

def failopen(src):
    t = _ast(src); n = 0
    for nd in (ast.walk(t) if t else []):
        if isinstance(nd, ast.FunctionDef) and re.search(r"auth|valid|check|verify|allow|permit", nd.name, re.I):
            n += sum(1 for x in ast.walk(nd) if isinstance(x, ast.Return) and isinstance(x.value, ast.Constant) and x.value.value is True)
    return n

def changed_lines(files):
    for f in files:
        path = fpath(f)
        for h in f["hunks"]:
            ln = h["ns"]
            for c, t in h["lines"]:
                if c == "+": yield path, "+", t, ln; ln += 1
                elif c == "-": yield path, "-", t, ln
                else: ln += 1

def is_test(p): return p.startswith("tests/") or os.path.basename(p).startswith("test_")

def static_analysis(files, changes):
    items, checks = [], []
    for p, c in changes.items():
        if c is not None and p.endswith(".py"):
            ok = _ast(c) is not None
            checks.append({"check": "python_syntax", "path": p, "result": "PASSED" if ok else "FAILED"})
            if not ok: items.append({"severity": "CRITICAL", "rule": "SYNTAX_ERROR", "path": p})
    for p, c, t, ln in changed_lines(files):
        if c == "+" and SECRET_RE.search(t): items.append({"severity": "CRITICAL", "rule": "SECRET_IN_PATCH", "path": p, "line": ln, "evidence": "[value withheld]"})
    checks.append({"check": "secret_scan_added_lines", "result": "FAILED" if any(i["rule"] == "SECRET_IN_PATCH" for i in items) else "PASSED"})
    checks.append({"check": "lint_typecheck", "result": "NOT_RUN", "reason": "no linter configured in this standalone build"})
    return {"checks": checks, "findings": items}

def patch_breaker(files, changes, root):
    F, C = [], []
    def chk(i, d, out, ev="", lim=""): C.append({"id": i, "description": d, "outcome": out, "evidence": ev, "limitation": lim})
    def find(sev, rule, path, ev, line=None): F.append({"id": f"PB-{len(F)+1:02d}", "severity": sev, "rule": rule, "path": path, "line": line, "evidence": redact(ev)[:200]})
    lines = list(changed_lines(files)); n0 = len(F)
    for p, c, t, ln in lines:
        if c == "-" and re.search(r"\b(raise|assert)\b|validate|sanitize", t) and not is_test(p): find("HIGH", "REMOVED_VALIDATION", p, t.strip(), ln)
    chk("R1", "removed validation/raise/assert in source", "BREAK_FOUND" if len(F) > n0 else "NO_BREAK", "diff scan"); n0 = len(F)
    for p, c, t, ln in lines:
        if c == "+" and UNSAFE_RE.search(t): find("HIGH", "UNSAFE_PATTERN_ADDED", p, t.strip(), ln)
        if c == "+" and SECRET_RE.search(t): find("CRITICAL", "SECRET_IN_PATCH", p, "[withheld]", ln)
    chk("R2", "unsafe patterns / secrets added", "BREAK_FOUND" if len(F) > n0 else "NO_BREAK", "diff scan"); n0 = len(F)
    for p, new in changes.items():
        if not p.endswith(".py") or new is None: continue
        fp = os.path.join(root, p); old = open(fp, encoding="utf-8").read() if os.path.isfile(fp) else ""
        if silent_handlers(new) > silent_handlers(old): find("HIGH", "ERROR_SWALLOWED", p, "new broad except without re-raise (hides error rather than fixing cause)")
        if failopen(new) > failopen(old): find("HIGH", "FAIL_OPEN", p, "new `return True` inside auth/validate/check-style function")
    chk("R3", "AST: swallowed errors & fail-open returns (before vs after)", "BREAK_FOUND" if len(F) > n0 else "NO_BREAK", "ast compare", "Python only"); n0 = len(F)
    for p, c, t, ln in lines:
        if is_test(p) and c == "+" and re.search(r"skip|assert\s+True\b|xfail", t): find("HIGH", "TEST_WEAKENED", p, t.strip(), ln)
        if is_test(p) and c == "-" and re.search(r"\bassert", t): find("HIGH", "TEST_ASSERTION_REMOVED", p, t.strip(), ln)
        if is_test(p) and c == "+" and re.search(r"mock|patch\(", t, re.I): find("MEDIUM", "MOCK_ADDED_IN_TEST", p, t.strip(), ln)
    chk("R4", "tests skipped/mocked/assertions removed", "BREAK_FOUND" if len(F) > n0 else "NO_BREAK", "diff scan"); n0 = len(F)
    src = [p for p in changes if not is_test(p) and p.endswith(".py")]
    if src and not any(is_test(p) for p in changes): find("MEDIUM", "NO_NEGATIVE_TESTS_ADDED", src[0], "source changed, no test file changed in patch")
    chk("R5", "patch adds tests for the change", "BREAK_FOUND" if len(F) > n0 else "NO_BREAK", "path scan"); n0 = len(F)
    for p in changes:
        if re.search(r"requirements|pyproject|setup\.py|package\.json|poetry", p): find("MEDIUM", "DEPENDENCY_CHANGE", p, "dependency manifest changed; versions/advisories not verified (offline)")
    chk("R6", "dependency/version assumptions", "BREAK_FOUND" if len(F) > n0 else "NO_BREAK", "path scan", "no advisory DB offline")
    chk("R7", "patch fixes stated failure mode (not just example)", "NEEDS_REVIEW", "not decidable deterministically", "requires reproducer tests; see audit")
    chk("R8", "alternate code paths bypassing fix", "NEEDS_REVIEW", "not analysed", "no call-graph analysis")
    return {"status": "BREAK_FOUND" if F else "NO_BREAK_FOUND_WITHIN_SCOPE", "findings": F, "checks": C, "note": "Never 'unbreakable'; scope = rules R1-R6 + executed tests."}

_NETISO = None
def net_isolation():
    global _NETISO
    if _NETISO is None:
        try: _NETISO = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
        except Exception: _NETISO = False
    return _NETISO

def exec_enabled(): return os.environ.get("IRA_ALLOW_LOCAL_EXEC") == "1"

def parse_unittest(out, code, timed_out):
    ran = re.search(r"Ran (\d+) tests?", out); ran = int(ran[1]) if ran else 0
    sk = re.search(r"skipped=(\d+)", out); fl = re.search(r"failures=(\d+)", out); er = re.search(r"errors=(\d+)", out)
    s = {"ran": ran, "skipped": int(sk[1]) if sk else 0, "failures": int(fl[1]) if fl else 0, "errors": int(er[1]) if er else 0}
    if timed_out: st = "INCONCLUSIVE"
    elif code == 0 and ran > 0: st = "PASSED"
    elif code != 0: st = "FAILED"
    else: st = "INCONCLUSIVE"
    return st, s

def run_cmd(cmd, cwd, timeout=30, cap=20000, allowed=None):
    allowed = ALLOWED_CMDS if allowed is None else allowed
    r = {"command": cmd, "cwd": "<temp copy>", "started": now()}
    if cmd not in allowed: r.update(status="BLOCKED", reason="command not in operator allowlist"); return r
    if not exec_enabled():
        r.update(status="BLOCKED", reason="runtime execution disabled: no container sandbox available; set IRA_ALLOW_LOCAL_EXEC=1 to opt in to process-level execution of operator-approved fixtures"); return r
    env = {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", HOME=cwd)
    argv = [sys.executable] + cmd[1:]; net = net_isolation()
    if net: argv = ["unshare", "-rn"] + argv
    def pre():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5)); resource.setrlimit(resource.RLIMIT_FSIZE, (10**7, 10**7))
    t0 = time.monotonic()
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, preexec_fn=pre, start_new_session=True)
    to = False
    try: out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        to = True
        try: os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        out, _ = p.communicate()
    try: os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError): pass
    txt = redact(out[:cap].decode("utf-8", "replace")); st, summ = parse_unittest(txt, p.returncode, to)
    r.update(status=st, exit_code=p.returncode, duration_s=round(time.monotonic() - t0, 3), timed_out=to, summary=summ, output=txt,
             output_sha256=sha(txt), network_isolated=net, ended=now(), tool={"python": sys.version.split()[0]})
    return r

def not_run(reason): return {"command": TEST_CMD, "status": "NOT_RUN", "reason": reason}

def sign_warrant(w, key=TEST_KEY): return hmac.new(key, canon({k: v for k, v in w.items() if k != "mac"}), "sha256").hexdigest()

def make_test_warrant(repo_id, base_sha, patch_hash, scope, actions=("static", "test_execution"), ttl_s=3600, **over):
    w = {"warrant_id": "TESTW-" + uuid.uuid4().hex[:12], "repo_id": repo_id, "base_sha": base_sha, "patch_hash": patch_hash, "path_scope": list(scope),
         "allowed_actions": list(actions), "expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=ttl_s)).isoformat(),
         "policy_version": "ira-policy-1", "issuer": "TEST-ONLY-LOCAL-FIXTURE", "nonce": uuid.uuid4().hex, "status": "ACTIVE", "test_only": True}
    w.update(over); w["mac"] = sign_warrant(w); return w

def check_warrant(w, ctx, revoked=()):
    r = {"status": None, "reasons": [], "warrant_id": None, "test_only": None, "checked_at": now(), "scope": None, "expires_at": None, "action": ctx.get("action")}
    def fail(s, why): r["status"] = s; r["reasons"].append(why); return r
    if not w: return fail("NO_WARRANT", "no warrant supplied: NEEDS_AUTHORIZATION")
    need = ("warrant_id", "repo_id", "base_sha", "patch_hash", "path_scope", "allowed_actions", "expires_at", "policy_version", "issuer", "nonce", "status", "mac")
    if not isinstance(w, dict) or any(k not in w for k in need) or not isinstance(w["path_scope"], list) or not isinstance(w["allowed_actions"], list):
        return fail("MALFORMED", "missing/invalid fields")
    r.update(warrant_id=w["warrant_id"], test_only=bool(w.get("test_only")), scope=w["path_scope"], expires_at=w["expires_at"])
    key = os.environ.get("IRA_WARRANT_KEY", "").encode() or (TEST_KEY if w.get("test_only") else b"")
    if not key or not hmac.compare_digest(sign_warrant(w, key), str(w["mac"])): return fail("BAD_MAC", "integrity check failed or no verification key")
    if w["status"] == "REVOKED" or w["warrant_id"] in revoked: return fail("REVOKED", "warrant revoked")
    try: exp = dt.datetime.fromisoformat(w["expires_at"])
    except Exception: return fail("MALFORMED", "bad expires_at")
    if exp <= dt.datetime.now(dt.timezone.utc): return fail("EXPIRED", "expired at " + w["expires_at"])
    if any(s in ("*", "**", "", ".", "**/*") for s in w["path_scope"]) or "*" in w["allowed_actions"]: return fail("OVER_BROAD", "wildcard scope/actions not accepted")
    for k in ("repo_id", "base_sha", "patch_hash"):
        if w[k] != ctx[k]: return fail("MISMATCH", f"{k} differs from request (warrant does not authorize this artifact)")
    if ctx.get("action") not in w["allowed_actions"]: return fail("MISMATCH", f"action {ctx.get('action')} not permitted")
    out = [p for p in ctx["paths"] if not any(fnmatch.fnmatch(p, s) for s in w["path_scope"])]
    if out: return fail("MISMATCH", "paths outside scope: " + ", ".join(out))
    r["status"] = "VALID"; r["reasons"].append("authorized within scope; this is NOT a technical-correctness result"); return r

def audit(req, ident, before, after):
    claim, F = req.get("claim") or {}, []
    def f(i, sev, claimed, observed, ev=None): F.append({"id": i, "severity": sev, "claimed": claimed, "observed": observed, "evidence_ref": ev})
    a, b = after["status"], before["status"]
    if claim.get("tests_passed") is True:
        if a == "PASSED": f("A-CLAIM-TESTS", "INFO", "tests passed", "confirmed by executed command", "ev:tests_after")
        elif a == "FAILED": f("A-CLAIM-TESTS", "HIGH", "tests passed", "executed tests FAILED (claim contradicted)", "ev:tests_after")
        else: f("A-CLAIM-TESTS", "HIGH", "tests passed", f"no execution evidence (status {a}); claim NOT trusted")
    f("A-BASE", "INFO" if ident["base_matches"] else "HIGH", "base " + str(req.get("base_sha"))[:12], "tested tree " + ident["tested_base_tree"][:12])
    cf = claim.get("files")
    if cf is not None and set(cf) != set(ident["changed_paths"]): f("A-FILES", "MEDIUM", sorted(cf), sorted(ident["changed_paths"]))
    if b == "FAILED" and a == "PASSED": f("A-BEFORE-AFTER", "INFO", "fix", "reproducer fails on base, passes on patched: fix demonstrated for supplied tests", "ev:tests_before,ev:tests_after")
    elif b == "PASSED" and a == "PASSED": f("A-BEFORE-AFTER", "MEDIUM", "fix", "no supplied test fails on base: fix of stated failure NOT demonstrated")
    elif b == "PASSED" and a == "FAILED": f("A-BEFORE-AFTER", "HIGH", "fix", "regression: passed on base, fails after patch", "ev:tests_after")
    else: f("A-BEFORE-AFTER", "MEDIUM", "fix", f"before={b}, after={a}: before/after comparison unavailable")
    sk = (after.get("summary") or {}).get("skipped", 0)
    if sk: f("A-SKIPPED", "MEDIUM", "all tests ran", f"{sk} skipped", "ev:tests_after")
    f("A-STATIC-BASELINE", "INFO", "static before/after", "NOT_RUN: baseline comparison unsupported")
    st = "DISCREPANCIES" if any(x["severity"] == "HIGH" for x in F) else ("CONFIRMED" if a == "PASSED" else "INCONCLUSIVE")
    return {"status": st, "findings": F}

RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3, "UNKNOWN": 2}
def residual_risk(c):
    F = []
    def f(n, l, why): F.append({"factor": n, "level": l, "rationale": why})
    a = c["after"]["status"]
    f("tests", {"PASSED": "LOW", "FAILED": "CRITICAL"}.get(a, "UNKNOWN"), f"after-patch tests {a}")
    if (c["after"].get("summary") or {}).get("skipped"): f("skipped_tests", "MODERATE", "skipped tests reduce confidence")
    for sv, lv in (("CRITICAL", "CRITICAL"), ("HIGH", "HIGH"), ("MEDIUM", "MODERATE")):
        if any(x["severity"] == sv for x in c["breaker"]["findings"]): f("patch_breaker", lv, f"{sv} findings present"); break
    else: f("patch_breaker", "LOW", "no rule hits (within rule scope only)")
    if any(x["severity"] == "CRITICAL" for x in c["static"]["findings"]): f("static_analysis", "CRITICAL", "syntax/secret findings")
    if any(re.search(r"auth|crypt|secret|security|login|permission|token", p, re.I) for p in c["paths"]): f("security_sensitive_files", "HIGH", "security-sensitive path changed")
    if any(not p.endswith(".py") for p in c["paths"]): f("unsupported_language", "UNKNOWN", "non-Python files not analysed")
    f("patch_size", "MODERATE" if c["lines"] > 200 else "LOW", f"{c['lines']} changed lines")
    f("sandbox", "MODERATE", "process-level isolation only, not a container")
    f("coverage", "LOW", "coverage not measured (untested paths unknown)")
    if c["warrant"]["status"] != "VALID": f("authority", "MODERATE" if c["warrant"]["status"] == "NO_WARRANT" else "HIGH", "warrant " + c["warrant"]["status"])
    if c["audit"]["status"] == "DISCREPANCIES": f("conflicting_evidence", "HIGH", "auditor found claim/reality discrepancies")
    known = max(RANK[x["level"]] for x in F if x["level"] != "UNKNOWN")
    unk = any(x["level"] == "UNKNOWN" for x in F)
    overall = "UNKNOWN" if (unk and known < 2) else ["LOW", "MODERATE", "HIGH", "CRITICAL"][known]
    act = {"LOW": "eligible for human approval via governance", "MODERATE": "human review recommended before approval", "HIGH": "do not proceed without remediation/review",
           "CRITICAL": "reject", "UNKNOWN": "gather missing evidence (run tests with a valid warrant) before any decision"}[overall]
    return {"overall": overall, "factors": F, "recommended_action": act, "note": "policy-based category, not a calibrated probability; missing evidence never lowers risk"}

def resolve_repo(root, name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."): raise PatchError("BAD_REPO", "invalid repo name")
    p = os.path.join(root, name)
    if not os.path.isdir(p): raise PatchError("BAD_REPO", "unknown repo")
    return p

def assess(req, data_dir, repo_root):
    run_id = "run_" + uuid.uuid4().hex[:12]; t_start = now(); patch_text = req.get("patch") or ""
    if not isinstance(patch_text, str): patch_text = ""
    ph = sha(patch_text)
    ident = {"repo_id": req.get("repo"), "declared_base_sha": req.get("base_sha"), "patch_hash": ph, "submitted_at": t_start, "changed_paths": [], "files": [], "base_matches": False, "tested_base_tree": ""}
    R = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "submitted_at": t_start, "request": {k: v for k, v in req.items() if k not in ("patch", "warrant")},
         "stages": [], "identity": ident, "static": {"checks": [], "findings": []}, "tests": {}, "breaker": {"status": "BLOCKED", "findings": [], "checks": []},
         "audit": {"status": "INCONCLUSIVE", "findings": []}, "warrant": {"status": "NO_WARRANT", "reasons": []}, "risk": None, "evidence": {}, "limitations": list(LIMITATIONS), "warranty_id": None}
    def st(name, status, detail=""): R["stages"].append({"stage": name, "status": status, "detail": detail, "at": now()})
    work = tempfile.mkdtemp(prefix="ira_", dir=os.environ.get("IRA_TMP_ROOT") or None)
    before = after = not_run("not reached"); changes, files, root, term = {}, [], None, None
    try:
        st("RECEIVED", "OK", f"patch {ph[:12]}, {len(patch_text)} chars")
        try:
            root = resolve_repo(repo_root, req.get("repo")); ident["tested_base_tree"] = tree_hash(root)
            ident["base_matches"] = bool(req.get("base_sha")) and req["base_sha"] == ident["tested_base_tree"]
            if not ident["base_matches"]: raise PatchError("BASE_MISMATCH", "declared base differs from tested tree (never silently testing another base)")
            files = parse_diff(patch_text); changes = apply_patch(files, root)
            ident["changed_paths"] = sorted(changes); ident["files"] = [{"path": fpath(f), "added": f["added"], "removed": f["removed"]} for f in files]
            st("IDENTITY_VALIDATION", "OK", "patch parses, paths safe, applies to declared base")
        except PatchError as e:
            st("IDENTITY_VALIDATION", "FAILED", e.code); R["error"] = {"code": e.code, "message": e.msg}
            term = ("BLOCKED" if e.code in ("BASE_MISMATCH", "BAD_REPO") else "REJECTED", f"identity validation failed: {e.code}")
        if not term:
            R["static"] = static_analysis(files, changes); st("STATIC_ANALYSIS", "OK", f"{len(R['static']['findings'])} findings")
            has_tests = os.path.isdir(os.path.join(root, "tests"))
            R["test_plan"] = {"command": TEST_CMD, "source": "operator allowlist + tests/ directory present" if has_tests else "no tests/ directory", "runnable": has_tests}
            st("TEST_PLAN", "OK" if has_tests else "WARN", R["test_plan"]["source"])
            ctx = lambda a: {"repo_id": req.get("repo"), "base_sha": req.get("base_sha"), "patch_hash": ph, "paths": ident["changed_paths"], "action": a}
            w = req.get("warrant")
            if not w and req.get("demo_warrant"): w = make_test_warrant(req["repo"], req["base_sha"], ph, ident["changed_paths"])
            R["warrant_is_demo"] = bool(req.get("demo_warrant")) and not req.get("warrant")
            rv = os.path.join(data_dir, "revoked.json"); revoked = set(json.load(open(rv))) if os.path.exists(rv) else set()
            wc = R["warrant"] = check_warrant(w, ctx("test_execution"), revoked)
            if not has_tests: before = after = not_run("no tests discovered")
            elif wc["status"] != "VALID": before = after = not_run("warrant " + wc["status"] + ": " + "; ".join(wc["reasons"]))
            else:
                b_dir, a_dir = os.path.join(work, "base"), os.path.join(work, "patched")
                materialize(root, b_dir); before = run_cmd(TEST_CMD, b_dir)
                wc = R["warrant"] = check_warrant(w, ctx("test_execution"), revoked)  # re-check before consequential execution
                if wc["status"] != "VALID": after = not_run("warrant re-check failed: " + wc["status"])
                else: materialize(root, a_dir, changes); after = run_cmd(TEST_CMD, a_dir)
            st("TEST_EXECUTION", after["status"], after.get("reason", ""))
            R["tests"] = {"before": before, "after": after}
            for k, v in (("tests_before", before), ("tests_after", after)):
                if "output" in v: R["evidence"]["ev:" + k] = {"kind": "test_output", "sha256": v["output_sha256"], "content": v["output"]}
            R["breaker"] = patch_breaker(files, changes, root); R["audit"] = audit(req, ident, before, after)
            st("INDEPENDENT_AUDIT", R["audit"]["status"], "breaker=" + R["breaker"]["status"])
            R["warrant_final"] = check_warrant(w, ctx("static"), revoked); st("WARRANT_CHECK", R["warrant"]["status"], "authority only; not correctness")
            R["risk"] = residual_risk({"after": after, "breaker": R["breaker"], "static": R["static"], "paths": ident["changed_paths"], "lines": sum(f["added"] + f["removed"] for f in files), "warrant": R["warrant"], "audit": R["audit"]})
            st("RESIDUAL_RISK", R["risk"]["overall"])
            sev = lambda s: any(x["severity"] == s for x in R["breaker"]["findings"] + R["static"]["findings"])
            if after["status"] == "FAILED" or sev("CRITICAL"): term = ("REJECTED", "after-patch tests failed or critical finding")
            elif R["warrant"]["status"] == "NO_WARRANT": term = ("NEEDS_HUMAN_REVIEW", "no warrant: NEEDS_AUTHORIZATION; tests NOT_RUN")
            elif R["warrant"]["status"] != "VALID": term = ("BLOCKED", "warrant " + R["warrant"]["status"])
            elif after["status"] == "BLOCKED": term = ("BLOCKED", after["reason"])
            elif after["status"] != "PASSED": term = ("NEEDS_HUMAN_REVIEW", f"tests {after['status']}")
            elif sev("HIGH") or R["audit"]["status"] == "DISCREPANCIES": term = ("NEEDS_HUMAN_REVIEW", "high-severity breaker finding or auditor discrepancy")
            elif R["risk"]["overall"] == "LOW": term = ("VERIFIED", "tests passed, no findings within scope")
            else: term = ("VERIFIED_WITH_WARNINGS", f"tests passed; residual risk {R['risk']['overall']}")
        else:
            R["risk"] = residual_risk({"after": before, "breaker": R["breaker"], "static": R["static"], "paths": [], "lines": 0, "warrant": R["warrant"], "audit": R["audit"]})
        R["status"], R["reason"] = term
        R["proof"] = build_proof(R, ph); st("PROOF_GENERATION", "OK", R["proof"]["proof_hash"][:16])
        if R["status"] in ("VERIFIED", "VERIFIED_WITH_WARNINGS"):
            from . import warranty
            R["warranty_id"] = warranty.create(R, root, changes, req.get("warranty_days", 30), data_dir)["warranty_id"]
        save_run(data_dir, R)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return R

def build_proof(R, ph):
    ident = R["identity"]; t = R.get("tests", {})
    cmds = [{"label": k, "command": v["command"], "status": v["status"], "exit_code": v.get("exit_code"), "started": v.get("started"), "ended": v.get("ended"), "duration_s": v.get("duration_s"),
             "summary": v.get("summary"), "reason": v.get("reason"), "evidence_ref": "ev:tests_" + k} for k, v in t.items()]
    p = {"proof_schema_version": SCHEMA_VERSION, "proof_id": "proof_" + uuid.uuid4().hex[:12], "run_id": R["run_id"], "repo_id": ident["repo_id"], "base_sha": ident["declared_base_sha"],
         "tested_base_tree": ident["tested_base_tree"], "patch_hash": ph, "changed_files": ident["files"], "path_scope": ident["changed_paths"], "claim": (R["request"].get("claim") or {}),
         "warrant": {k: R["warrant"].get(k) for k in ("warrant_id", "status", "scope", "expires_at", "test_only")}, "warrant_is_demo": R.get("warrant_is_demo", False),
         "tools": {"python": sys.version.split()[0], "runner": "ira process-level runner", "network_isolated": bool(t.get("after", {}).get("network_isolated"))},
         "commands_executed": cmds, "static_checks": R["static"]["checks"], "static_findings": R["static"]["findings"], "patch_breaker": {"status": R["breaker"]["status"], "findings": R["breaker"]["findings"], "checks": R["breaker"]["checks"]},
         "auditor": R["audit"], "residual_risk": R["risk"], "limitations": R["limitations"],
         "evidence": [{"ref": k, "kind": v["kind"], "sha256": v["sha256"]} for k, v in sorted(R["evidence"].items())],
         "overall_status": R["status"], "reason": R["reason"], "next_action": (R["risk"] or {}).get("recommended_action"),
         "note": "Assurance result only. Grants no permission to merge/deploy; governance (UNWIND) is separate."}
    return seal(p)

def proof_hash(p): return sha(canon({k: v for k, v in p.items() if k not in ("proof_hash", "attestation", "evidence_content")}))
def seal(p):
    p["proof_hash"] = proof_hash(p); key = os.environ.get("IRA_PROOF_HMAC_KEY", "").encode()
    p["attestation"] = {"type": "hmac-sha256", "value": hmac.new(key, p["proof_hash"].encode(), "sha256").hexdigest(), "note": "shared-secret MAC; not a public-key signature, no non-repudiation"} if key else \
        {"type": "none", "note": "hash-linked integrity proof only; NOT a digital signature"}
    return p
def verify_proof(p): return p.get("proof_hash") == proof_hash(p)
def export_proof(R): p = dict(R["proof"]); p["evidence_content"] = R["evidence"]; return p

def render_report(R):
    p = R["proof"]; L = [f"REPAIR PROOF {p['proof_id']}  (run {p['run_id']})", f"Status: {p['overall_status']} - {p['reason']}", f"Repo: {p['repo_id']}  base: {str(p['base_sha'])[:16]}  patch: {p['patch_hash'][:16]}",
         f"Integrity: {p['attestation']['type']} ({p['attestation']['note']})", f"proof_hash: {p['proof_hash']}", "", "Commands executed / checks:"]
    for c in p["commands_executed"]: L.append(f"  [{c['label']}] {c['status']} exit={c['exit_code']} {c.get('duration_s')}s {c.get('reason') or ''} -> {c['evidence_ref']}")
    L += ["", f"Patch Breaker: {p['patch_breaker']['status']}"] + [f"  {f['id']} {f['severity']} {f['rule']} {f['path']}: {f['evidence']}" for f in p["patch_breaker"]["findings"]]
    L += ["", f"Auditor: {p['auditor']['status']}"] + [f"  {f['id']} {f['severity']}: claimed={f['claimed']} observed={f['observed']}" for f in p["auditor"]["findings"]]
    L += ["", f"Warrant: {p['warrant']['status']} ({p['warrant']['warrant_id']}){' [DEMO test-only warrant]' if p['warrant_is_demo'] else ''}", "", f"Residual risk: {p['residual_risk']['overall']}"]
    L += [f"  {f['factor']}: {f['level']} - {f['rationale']}" for f in p["residual_risk"]["factors"]] + ["", "Next: " + str(p["next_action"]), "", "Limitations:"] + ["  - " + x for x in p["limitations"]]
    return "\n".join(L)

def save_run(d, R):
    os.makedirs(os.path.join(d, "runs"), exist_ok=True); json.dump(R, open(os.path.join(d, "runs", R["run_id"] + ".json"), "w"), indent=1)
def load_run(d, rid):
    if not re.fullmatch(r"run_[0-9a-f]{12}", rid or ""): raise PatchError("BAD_ID", str(rid))
    p = os.path.join(d, "runs", rid + ".json")
    if not os.path.exists(p): raise PatchError("NOT_FOUND", rid)
    return json.load(open(p))
