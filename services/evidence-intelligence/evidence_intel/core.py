"""AEGISNOVA Evidence Intelligence core (Python stdlib only)."""
import hashlib, json, re, socket, sqlite3, threading, urllib.error, urllib.parse, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

SCHEMA = "aegisnova.evidence-bundle/1"
MAX_BYTES = 1_000_000
OSV, GH, TAV = "https://api.osv.dev/v1", "https://api.github.com", "https://api.tavily.com/search"
ECO = {"PyPI": "pip", "npm": "npm", "crates.io": "rust", "Go": "go", "Maven": "maven", "RubyGems": "rubygems", "NuGet": "nuget"}
SOURCES = ("tavily", "osv", "ghsa")
FAIL = {"NOT_CONFIGURED", "AUTH_ERROR", "RATE_LIMITED", "TIMEOUT", "ERROR"}
PKG_RE = re.compile(r"^[@A-Za-z0-9][\w.@/:+-]{0,213}$")
VER_RE = re.compile(r"^[\w.+!~-]{1,64}$")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}-[\w.:-]{3,60}$")
SECRET_RE = re.compile(r"(ghp_|gho_|ghs_|github_pat_|tvly-)[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+", re.I)
DEFAULTS = {"fresh_hours": 24, "aging_hours": 72, "stale_hours": 168, "timeout": 10, "max_results": 5}
FRESH_ORDER = ["EXPIRED", "SOURCE_UNAVAILABLE", "CHANGED", "STALE", "NOT_REVALIDATED", "DATE_UNKNOWN", "AGING", "FRESH"]

class ValidationError(ValueError):
    pass

class ProviderError(Exception):
    def __init__(self, status, detail=""):
        super().__init__(detail); self.status, self.detail = status, detail

def redact(s): return SECRET_RE.sub("[REDACTED]", str(s))
def clean(s, n=600): return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(s or ""))[:n]
def utcnow(): return datetime.now(timezone.utc)
def iso(d): return d.strftime("%Y-%m-%dT%H:%M:%SZ")
def parse_dt(s):
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def canon_url(u):
    try:
        p = urllib.parse.urlparse(str(u).strip())
        if p.scheme not in ("http", "https") or not p.netloc: return ""
        q = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.lower().startswith("utm_")])
        return urllib.parse.urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", q, ""))
    except Exception:
        return ""

def validate(d):
    if not isinstance(d, dict): raise ValidationError(["body must be a JSON object"])
    errs = []
    eco, pkg, ver, adv = d.get("ecosystem"), d.get("package"), d.get("version") or None, d.get("advisory_id") or None
    if pkg or ver or eco:
        if eco not in ECO: errs.append("ecosystem must be one of " + ", ".join(ECO))
        if not isinstance(pkg, str) or not PKG_RE.match(pkg): errs.append("invalid package name")
        if ver is not None and (not isinstance(ver, str) or not VER_RE.match(ver)): errs.append("invalid version")
    if adv is not None and (not isinstance(adv, str) or not ID_RE.match(adv)): errs.append("invalid advisory_id")
    if not pkg and not adv: errs.append("package (with ecosystem) or advisory_id is required")
    src = d.get("sources") or list(SOURCES)
    if not isinstance(src, list) or not set(src) <= set(SOURCES): errs.append("sources must be a subset of " + ",".join(SOURCES))
    try: mr = max(1, min(10, int(d.get("max_results", 5))))
    except Exception: errs.append("max_results must be an integer"); mr = 5
    if errs: raise ValidationError(errs)
    return {"ecosystem": eco, "package": pkg, "version": ver, "advisory_id": adv.upper() if adv else None, "sources": [s for s in SOURCES if s in src], "max_results": mr}

def default_http(method, url, headers=None, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "aegisnova-evidence-intel/0.1", "Accept": "application/json", **(headers or {})}
    if data: h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout) as r:
            raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES: raise ProviderError("ERROR", "response exceeded size bound")
            return r.status, json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, None
    except (socket.timeout, TimeoutError):
        raise ProviderError("TIMEOUT", "request timed out")
    except urllib.error.URLError as e:
        raise ProviderError("TIMEOUT" if isinstance(e.reason, socket.timeout) else "ERROR", "network error: " + redact(e.reason))
    except ValueError:
        raise ProviderError("ERROR", "malformed JSON response")

def bad(st):
    if st in (429, 432, 433): return "RATE_LIMITED", f"HTTP {st} rate limit/quota"
    if st == 401: return "AUTH_ERROR", "HTTP 401 invalid credentials"
    if st == 403: return "RATE_LIMITED", "HTTP 403 (rate limit or forbidden)"
    if st >= 400 and st != 404: return "ERROR", f"HTTP {st}"
    return None

def mk(provider, source_id, url, title, now, kind="advisory", **kw):
    u = canon_url(url)
    r = {"provider": provider, "source_id": source_id, "kind": kind, "url": u, "title": clean(title, 200),
         "publisher": urllib.parse.urlparse(u).netloc, "ids": [], "package": None, "ranges": [], "fixed_versions": [],
         "severity": None, "published": None, "modified": None, "snippet": "", "provider_score": None, "references": [],
         "limitations": [], "retrieved_at": iso(now), "first_retrieved_at": iso(now), "last_validated_at": iso(now), "untrusted": True}
    r.update(kw)
    core = {k: r[k] for k in ("provider", "source_id", "url", "title", "ids", "package", "ranges", "fixed_versions", "severity", "published", "modified", "snippet")}
    r["content_hash"] = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    return r

def normname(eco, n): return re.sub(r"[-_.]+", "-", n.lower()) if eco in ("PyPI", None) else (n or "").lower()

def osv_rec(v, req, now):
    ranges, fixed, pkgs = [], [], []
    for a in v.get("affected") or []:
        p = a.get("package") or {}
        pkgs.append({"ecosystem": p.get("ecosystem"), "name": p.get("name")})
        for r in a.get("ranges") or []:
            intro = None
            for e in r.get("events") or []:
                if "introduced" in e: intro = e["introduced"]
                if "fixed" in e:
                    ranges.append({"type": r.get("type"), "introduced": intro, "fixed": e["fixed"]}); fixed.append(e["fixed"]); intro = None
            if intro is not None: ranges.append({"type": r.get("type"), "introduced": intro, "fixed": None})
    want = normname(req.get("ecosystem"), req.get("package") or "")
    pkg = next((p for p in pkgs if p["name"] and normname(req.get("ecosystem"), p["name"]) == want), pkgs[0] if pkgs else None)
    sev = (v.get("database_specific") or {}).get("severity")
    lim = ["OSV 'last_affected' events and non-introduced/fixed range semantics are not interpreted"]
    return mk("osv", v["id"], f"https://osv.dev/vulnerability/{urllib.parse.quote(v['id'])}", v.get("summary") or v["id"], now,
              ids=[v["id"]] + [a for a in v.get("aliases") or [] if isinstance(a, str)], package=pkg, ranges=ranges,
              fixed_versions=sorted(set(fixed)), severity=sev.upper() if isinstance(sev, str) else None,
              published=v.get("published"), modified=v.get("modified"), snippet=clean(v.get("details") or ""),
              references=[x["url"] for x in v.get("references") or [] if isinstance(x, dict) and x.get("url")][:10], limitations=lim)

def p_osv(req, ctx):
    http, to, now, vulns = ctx["http"], ctx["timeout"], ctx["now"], []
    if req.get("package"):
        body = {"package": {"name": req["package"], "ecosystem": req["ecosystem"]}}
        if req.get("version"): body["version"] = req["version"]
        st, j = http("POST", OSV + "/query", None, body, to)
        if bad(st): return (*bad(st), [])
        if not isinstance(j, dict): return "ERROR", "malformed OSV response", []
        vulns += [v for v in j.get("vulns") or [] if isinstance(v, dict) and isinstance(v.get("id"), str)]
    if req.get("advisory_id"):
        st, j = http("GET", OSV + "/vulns/" + urllib.parse.quote(req["advisory_id"]), None, None, to)
        if bad(st): return (*bad(st), [])
        if st == 200 and isinstance(j, dict) and isinstance(j.get("id"), str): vulns.append(j)
    seen, recs = set(), []
    for v in vulns[:25]:
        if v["id"] not in seen: seen.add(v["id"]); recs.append(osv_rec(v, req, now))
    return "OK", "", recs

def ghsa_rec(a, req, now):
    vs = [v for v in a.get("vulnerabilities") or [] if isinstance(v, dict)]
    want = normname(req.get("ecosystem"), req.get("package") or "")
    def pk(v): p = v.get("package") or {}; return {"ecosystem": p.get("ecosystem"), "name": p.get("name")}
    pick = next((v for v in vs if (v.get("package") or {}).get("name") and normname(req.get("ecosystem"), v["package"]["name"]) == want), vs[0] if vs else None)
    ranges, fixed = [], []
    for v in vs if not pick else [pick]:
        fp = v.get("first_patched_version")
        fp = fp.get("identifier") if isinstance(fp, dict) else fp
        ranges.append({"type": "GHSA_RANGE_EXPR", "expr": v.get("vulnerable_version_range"), "fixed": fp})
        if fp: fixed.append(fp)
    sev = a.get("severity")
    ids = [a["ghsa_id"]] + ([a["cve_id"]] if a.get("cve_id") else [])
    refs = [x if isinstance(x, str) else (x or {}).get("url") for x in a.get("references") or []]
    return mk("ghsa", a["ghsa_id"], a.get("html_url") or f"https://github.com/advisories/{a['ghsa_id']}", a.get("summary") or a["ghsa_id"], now,
              ids=ids, package=pk(pick) if pick else None, ranges=ranges, fixed_versions=sorted(set(fixed)),
              severity=sev.upper() if isinstance(sev, str) else None, published=a.get("published_at"), modified=a.get("updated_at"),
              snippet=clean(a.get("description") or ""), references=[r for r in refs if r][:10],
              limitations=["GitHub range expressions are stored verbatim and not evaluated"])

def p_ghsa(req, ctx):
    http, to, now, env = ctx["http"], ctx["timeout"], ctx["now"], ctx["env"]
    hd = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if env.get("GITHUB_TOKEN"): hd["Authorization"] = "Bearer " + env["GITHUB_TOKEN"]
    advs, note = [], "" if env.get("GITHUB_TOKEN") else "unauthenticated (low rate limit)"
    if req.get("package"):
        aff = req["package"] + ("@" + req["version"] if req.get("version") else "")
        q = urllib.parse.urlencode({"ecosystem": ECO[req["ecosystem"]], "affects": aff, "per_page": min(30, req["max_results"] * 3)})
        st, j = http("GET", GH + "/advisories?" + q, hd, None, to)
        if bad(st): return (*bad(st), [])
        if not isinstance(j, list): return "ERROR", "malformed GHSA response", []
        advs += j
    aid = req.get("advisory_id")
    if aid and aid.startswith("GHSA-"):
        st, j = http("GET", GH + "/advisories/" + urllib.parse.quote(aid), hd, None, to)
        if bad(st): return (*bad(st), [])
        if st == 200 and isinstance(j, dict): advs.append(j)
    elif aid and aid.startswith("CVE-"):
        st, j = http("GET", GH + "/advisories?" + urllib.parse.urlencode({"cve_id": aid}), hd, None, to)
        if bad(st): return (*bad(st), [])
        if isinstance(j, list): advs += j
    seen, recs = set(), []
    for a in advs:
        if isinstance(a, dict) and isinstance(a.get("ghsa_id"), str) and a["ghsa_id"] not in seen:
            seen.add(a["ghsa_id"]); recs.append(ghsa_rec(a, req, now))
    return "OK", note, recs[:25]

def p_tavily(req, ctx):
    key = ctx["env"].get("TAVILY_API_KEY")
    if not key: return "NOT_CONFIGURED", "TAVILY_API_KEY not set", []
    q = (f"{req['package']} {req['ecosystem']} {req.get('version') or ''} security vulnerability advisory CVE" if req.get("package")
         else f"{req['advisory_id']} vulnerability advisory affected fixed versions")
    body = {"query": " ".join(q.split()), "max_results": req["max_results"], "search_depth": "basic", "include_raw_content": False}
    st, j = ctx["http"]("POST", TAV, {"Authorization": "Bearer " + key}, body, ctx["timeout"])
    if bad(st): return (*bad(st), [])
    if not isinstance(j, dict) or not isinstance(j.get("results"), list): return "ERROR", "malformed Tavily response", []
    recs = []
    for x in j["results"][:req["max_results"]]:
        if not isinstance(x, dict) or not canon_url(x.get("url")): continue
        sc = x.get("score")
        recs.append(mk("tavily", canon_url(x["url"]), x["url"], x.get("title") or x["url"], ctx["now"], kind="discovery",
                       snippet=clean(x.get("content")), provider_score=sc if isinstance(sc, (int, float)) else None,
                       ids=sorted(set(m.upper() for m in re.findall(r"CVE-\d{4}-\d{4,}|GHSA(?:-[2-9cfghjmpqrvwx]{4}){3}", clean(x.get("content")), re.I))),
                       limitations=["Search snippet is discovery evidence; linked source not verified", "provider_score is relevance only, not truth"]))
    return "OK", "", recs

PROVIDERS = {"tavily": p_tavily, "osv": p_osv, "ghsa": p_ghsa}

def run_provider(name, req, ctx):
    try: st, detail, recs = PROVIDERS[name](req, ctx)
    except ProviderError as e: st, detail, recs = e.status, e.detail, []
    except Exception as e: st, detail, recs = "ERROR", f"{type(e).__name__}: {e}", []
    if st == "OK" and not recs: st = "EMPTY"
    return {"name": name, "status": st, "detail": redact(detail), "records": recs}

def vt(s, n=8):
    if not s or not re.fullmatch(r"\d+(\.\d+)*", str(s)): return None
    t = tuple(int(x) for x in s.split("."))
    return t + (0,) * (n - len(t)) if len(t) <= n else None

def applicability(r, req):
    v = vt(req.get("version"))
    rs = [x for x in r["ranges"] if x.get("type") in ("ECOSYSTEM", "SEMVER")]
    if v is None or not rs: return "NOT_EVALUATED"
    hits = []
    for x in rs:
        lo = (0,) * 8 if x.get("introduced") in (None, "0") else vt(x["introduced"])
        hi = vt(x["fixed"]) if x.get("fixed") else None
        if lo is None or (x.get("fixed") and hi is None): return "NOT_EVALUATED"
        hits.append(lo <= v and (hi is None or v < hi))
    return "IN_LISTED_RANGE" if any(hits) else "NOT_IN_LISTED_RANGES"

def origin(r): return "github" if r["provider"] == "ghsa" or r["source_id"].upper().startswith("GHSA-") else r["provider"]

def reconcile(records, req):
    adv, par = [r for r in records if r["kind"] == "advisory"], {}
    def f(x):
        par.setdefault(x, x)
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for r in adv:
        ids = [i.upper() for i in r["ids"]] or [r["source_id"].upper()]
        for i in ids[1:]: par[f(i)] = f(ids[0])
        f(ids[0])
    groups = {}
    for r in adv: groups.setdefault(f((r["ids"] or [r["source_id"]])[0].upper()), []).append(r)
    out, want = [], normname(req.get("ecosystem"), req.get("package") or "")
    for gid, rs in sorted(groups.items()):
        conf = []
        def chk(field, vals):
            if len({json.dumps(v) for v in vals.values()}) > 1: conf.append({"field": field, "values": vals})
        chk("fixed_versions", {r["citation"]: r["fixed_versions"] for r in rs if r["fixed_versions"]})
        chk("severity", {r["citation"]: r["severity"] for r in rs if r["severity"]})
        chk("published_date", {r["citation"]: r["published"][:10] for r in rs if r["published"]})
        mm = {r["citation"]: r["package"]["name"] for r in rs if want and r["package"] and r["package"].get("name") and normname(req.get("ecosystem"), r["package"]["name"]) != want}
        if mm: conf.append({"field": "package_identity", "values": mm})
        org = sorted({origin(r) for r in rs})
        state = "CONFLICTING" if conf else "CORROBORATED" if len(org) >= 2 else "CONSISTENT" if len(rs) >= 2 else "PARTIALLY_SUPPORTED"
        why = {"CONFLICTING": "Sources disagree; original values preserved, none chosen.", "CORROBORATED": "Agreeing records from independent origins.",
               "CONSISTENT": "Records agree but share one upstream origin (mirrors), so not independent corroboration.",
               "PARTIALLY_SUPPORTED": "Single source record."}[state]
        out.append({"group_id": gid, "ids": sorted({i for r in rs for i in (r["ids"] or [r["source_id"]])}), "state": state, "citations": sorted(r["citation"] for r in rs),
                    "independent_origins": org, "conflicts": conf, "applicability": {r["citation"]: applicability(r, req) for r in rs},
                    "ranges_comparison": "NOT_EVALUATED (range syntaxes differ across providers; compared fixed versions, severity, dates only)", "rationale": why})
    disc = [r["citation"] for r in records if r["kind"] == "discovery"]
    if disc: out.append({"group_id": "discovery", "ids": [], "state": "UNRESOLVED", "citations": disc, "independent_origins": [], "conflicts": [], "applicability": {},
                         "ranges_comparison": "NOT_EVALUATED", "rationale": "Search snippets are discovery evidence; claims in them are unsupported until verified at the linked source. Relevance score is not confidence."})
    ast = [g["state"] for g in out if g["group_id"] != "discovery"]
    overall = next((s for s in ("CONFLICTING", "PARTIALLY_SUPPORTED", "CONSISTENT", "CORROBORATED") if s in ast), "UNRESOLVED" if disc else "INSUFFICIENT_EVIDENCE")
    return {"overall": overall, "groups": out}

def freshness(records, provs, now, cfg, changed):
    per, vals = {}, []
    for r in records:
        if r.get("carried_over") or provs.get(r["provider"], {}).get("status") in FAIL: s = "SOURCE_UNAVAILABLE"
        elif r["provider"] in changed: s = "CHANGED"
        elif not r.get("last_validated_at"): s = "NOT_REVALIDATED"
        elif not (r["published"] or r["modified"]): s = "DATE_UNKNOWN"
        else:
            h = (now - parse_dt(r["last_validated_at"])).total_seconds() / 3600
            s = "FRESH" if h <= cfg["fresh_hours"] else "AGING" if h <= cfg["aging_hours"] else "STALE" if h <= cfg["stale_hours"] else "EXPIRED"
        per[r["citation"]] = s; vals.append(s)
    return {"overall": next((s for s in FRESH_ORDER if s in vals), "NO_RECORDS"), "per_record": per, "thresholds_hours": {k: cfg[k] for k in ("fresh_hours", "aging_hours", "stale_hours")},
            "freshness_basis": "age of last successful provider validation; source publish/update dates are tracked separately"}

def diff(prev, records, provs):
    out = {}
    for n, p in provs.items():
        if p["status"] in FAIL: out[n] = {"state": "SOURCE_UNAVAILABLE", "detail": "latest check failed; prior records preserved"}; continue
        op = prev["providers"].get(n)
        if not op or op["status"] in FAIL: out[n] = {"state": "UNCOMPARABLE", "detail": "no successful prior check"}; continue
        old = {r["source_id"]: r for r in prev["records"] if r["provider"] == n and not r.get("carried_over")}
        new = {r["source_id"]: r for r in records if r["provider"] == n and not r.get("carried_over")}
        chg = {k: [{"field": f, "old": old[k][f], "new": new[k][f]} for f in ("title", "fixed_versions", "severity", "ranges", "modified", "snippet") if old[k][f] != new[k][f]]
               for k in new if k in old and new[k]["content_hash"] != old[k]["content_hash"]}
        added, removed = sorted(set(new) - set(old)), sorted(set(old) - set(new))
        out[n] = {"state": "MATERIAL_CHANGE" if (added or removed or chg) else "UNCHANGED", "added": added, "changed": chg,
                  "absent_in_latest": removed, "detail": "absent records are not confirmed removals" if removed else ""}
    st = [v["state"] for v in out.values()]
    return {"overall": next((s for s in ("MATERIAL_CHANGE", "SOURCE_UNAVAILABLE", "UNCOMPARABLE", "UNCHANGED") if s in st), "UNCOMPARABLE"), "providers": out}

def quality(records, rec, provs, req):
    adv = [r for r in records if r["kind"] == "advisory"]
    appl = [a for g in rec["groups"] for a in g["applicability"].values()]
    orgs = {o for g in rec["groups"] for o in g["independent_origins"]}
    conf = sum(len(g["conflicts"]) for g in rec["groups"])
    pkg_ok = bool(req.get("package")) and any(r["package"] and normname(req["ecosystem"], r["package"].get("name") or "") == normname(req["ecosystem"], req["package"]) for r in adv)
    miss = sorted({f for r in adv for f in ("severity", "fixed_versions", "published") if not r[f]})
    dims = {"authority": "advisory_database" if adv else "search_discovery_only" if records else "none", "directness": "direct" if adv else "indirect",
            "package_identity": "matched" if pkg_ok else "not_requested" if not req.get("package") else "unmatched",
            "version_applicability": "evaluated" if any(a != "NOT_EVALUATED" for a in appl) else "NOT_EVALUATED", "independent_origins": len(orgs),
            "conflicts": conf, "missing_fields": miss}
    ind = (40 if adv else 0) + (20 if len(orgs) >= 2 else 0) + (10 if pkg_ok else 0) + (10 if dims["version_applicability"] == "evaluated" else 0) + (10 if not miss and adv else 0) - 30 * min(conf, 1)
    return {"dimensions": dims, "indicator": max(0, min(100, ind)), "indicator_note": "Internal rule-based evidence-quality indicator; NOT a probability that claims are true."}

def next_action(rec, fr, df, provs):
    fails = [n for n, p in provs.items() if p["status"] in FAIL]
    if rec["overall"] == "CONFLICTING": return "Resolve conflicts manually against the primary advisory sources; do not rely on either value until verified."
    if fails and rec["overall"] in ("INSUFFICIENT_EVIDENCE", "UNRESOLVED"): return "Fix/retry unavailable providers (" + ", ".join(fails) + ") and refresh; absence of records is not evidence of safety."
    if df and df["overall"] == "MATERIAL_CHANGE": return "Review the snapshot diff; re-assess downstream decisions that used the previous snapshot."
    if fr["overall"] in ("STALE", "EXPIRED", "AGING", "SOURCE_UNAVAILABLE"): return "Run a manual refresh to revalidate sources."
    if rec["overall"] in ("INSUFFICIENT_EVIDENCE", "UNRESOLVED"): return "Verify discovery results at their linked primary sources; no advisory record was found, which does not mean the package is safe."
    return "Evidence is internally consistent for the sources queried; continue periodic revalidation."

class Service:
    def __init__(self, db=":memory:", http=default_http, env=None, clock=utcnow, cfg=None, demo=False):
        self.http, self.env, self.clock, self.demo = http, dict(env or {}), clock, demo
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.db = sqlite3.connect(db, check_same_thread=False); self.lock = threading.Lock(); self.last = {}
        with self.lock:
            self.db.executescript("CREATE TABLE IF NOT EXISTS research(id TEXT PRIMARY KEY, request TEXT, created TEXT);"
                                  "CREATE TABLE IF NOT EXISTS snapshots(research_id TEXT, seq INTEGER, created TEXT, bundle TEXT, PRIMARY KEY(research_id, seq));")

    def _run(self, req, now):
        ctx = {"http": self.http, "env": self.env, "timeout": self.cfg["timeout"], "now": now}
        with ThreadPoolExecutor(max_workers=3) as ex: res = list(ex.map(lambda n: run_provider(n, req, ctx), req["sources"]))
        for r in res: self.last[r["name"]] = r["status"]
        return res

    def _build(self, rid, req, results, now, prev):
        provs, records = {}, []
        for r in results:
            recs = r["records"]; carried = False
            if r["status"] in FAIL and prev:
                recs = [dict(x, carried_over=True) for x in prev["records"] if x["provider"] == r["name"]]; carried = bool(recs)
            ok = r["status"] in ("OK", "EMPTY")
            provs[r["name"]] = {"status": r["status"], "detail": r["detail"], "record_count": len(r["records"]), "carried_over": carried,
                                "checked_at": iso(now), "last_success_at": iso(now) if ok else (prev["providers"].get(r["name"], {}).get("last_success_at") if prev else None)}
            records += recs
        if prev:
            old = {(x["provider"], x["source_id"]): x for x in prev["records"]}
            for x in records:
                o = old.get((x["provider"], x["source_id"]))
                if o and not x.get("carried_over") and o["content_hash"] == x["content_hash"]: x["first_retrieved_at"] = o["first_retrieved_at"]
        records.sort(key=lambda x: (x["kind"] != "advisory", x["provider"], x["source_id"]))
        for i, x in enumerate(records, 1): x["citation"] = "SRC-%03d" % i; x["evidence_id"] = "EV-" + x["content_hash"][:12]
        df = diff(prev, records, provs) if prev else None
        changed = {n for n, v in (df or {"providers": {}})["providers"].items() if v["state"] == "MATERIAL_CHANGE"}
        fr = freshness(records, provs, now, self.cfg, changed); rec = reconcile(records, req); q = quality(records, rec, provs, req)
        lim = ["No provider result is ever interpreted as 'package is safe'.", "All web/provider content is untrusted data; instructions inside it are ignored.",
               "Version applicability uses simple numeric comparison only; otherwise NOT_EVALUATED."]
        if self.demo: lim.insert(0, "DEMO: fixture data, not live research.")
        return {"schema": SCHEMA, "research_id": rid, "mode": "DEMO_FIXTURES" if self.demo else "LIVE", "demo": self.demo, "generated_at": iso(now), "request": req,
                "identity": {"ecosystem": req.get("ecosystem"), "package": req.get("package"), "version": req.get("version"), "advisory_ids": sorted({i for g in rec["groups"] for i in g["ids"]} | ({req["advisory_id"]} if req.get("advisory_id") else set()))},
                "records": records, "citations": {x["citation"]: {"evidence_id": x["evidence_id"], "url": x["url"], "title": x["title"]} for x in records},
                "reconciliation": rec, "freshness": fr, "diff": df, "providers": provs, "quality": q,
                "snapshot_hash": hashlib.sha256("".join(sorted(x["content_hash"] for x in records)).encode()).hexdigest(),
                "limitations": lim, "recommended_next_action": next_action(rec, fr, df, provs)}

    def _save(self, rid, seq, b):
        with self.lock: self.db.execute("INSERT INTO snapshots VALUES(?,?,?,?)", (rid, seq, b["generated_at"], json.dumps(b))); self.db.commit()

    def research(self, raw):
        req = validate(raw); rid = "R-" + uuid.uuid4().hex[:10]; now = self.clock()
        with self.lock: self.db.execute("INSERT INTO research VALUES(?,?,?)", (rid, json.dumps(req), iso(now))); self.db.commit()
        b = self._build(rid, req, self._run(req, now), now, None); b["snapshot_seq"] = 1; self._save(rid, 1, b); return b

    def _snaps(self, rid):
        with self.lock: rows = self.db.execute("SELECT bundle FROM snapshots WHERE research_id=? ORDER BY seq", (rid,)).fetchall()
        if not rows: raise KeyError(rid)
        return [json.loads(r[0]) for r in rows]

    def get(self, rid): return self._snaps(rid)[-1]

    def refresh(self, rid):
        snaps = self._snaps(rid); prev = snaps[-1]; now = self.clock()
        b = self._build(rid, prev["request"], self._run(prev["request"], now), now, prev); b["snapshot_seq"] = len(snaps) + 1
        self._save(rid, b["snapshot_seq"], b); return b

    def diff(self, rid): return self.get(rid)["diff"] or {"overall": "UNCOMPARABLE", "providers": {}, "detail": "no refresh yet"}

    def evidence(self, eid):
        with self.lock: ids = [r[0] for r in self.db.execute("SELECT id FROM research").fetchall()]
        for rid in ids:
            for x in self.get(rid)["records"]:
                if x["evidence_id"] == eid: return x
        raise KeyError(eid)

    def export(self, rid): return {"export_format": "aegisnova.evidence-export/1", "bundle": self.get(rid)}

    def health(self):
        def st(n, conf):
            l = self.last.get(n)
            return "NOT_CONFIGURED" if not conf else "UNKNOWN" if l is None else "HEALTHY" if l in ("OK", "EMPTY") else "DEGRADED" if l == "RATE_LIMITED" else "UNAVAILABLE"
        t, g = bool(self.env.get("TAVILY_API_KEY")), bool(self.env.get("GITHUB_TOKEN"))
        return {"mode": "DEMO_FIXTURES" if self.demo else "LIVE", "note": "Status reflects the last actual request; no background probing.",
                "providers": {"tavily": {"configured": t, "status": st("tavily", t), "last_result": self.last.get("tavily")},
                              "osv": {"configured": True, "status": st("osv", True), "last_result": self.last.get("osv")},
                              "ghsa": {"configured": True, "token_set": g, "status": st("ghsa", True), "last_result": self.last.get("ghsa")}}}

    def settings(self):
        return {**self.cfg, "secrets": {"TAVILY_API_KEY": "set" if self.env.get("TAVILY_API_KEY") else "not set", "GITHUB_TOKEN": "set" if self.env.get("GITHUB_TOKEN") else "not set"}}
