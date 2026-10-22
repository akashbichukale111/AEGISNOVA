"""Input parsers. Supported: package.json, package-lock.json (v2/v3), requirements.txt, pyproject.toml,
generic service-map JSON. Everything else is rejected with an explicit UNSUPPORTED_FORMAT error."""
import hashlib, json, re, tomllib
from datetime import datetime
from .graph import Graph, sha

MAX_INPUT_BYTES = 2_000_000


class InputError(ValueError):
    def __init__(self, code, msg):
        super().__init__(msg); self.code = code


def _prov(name, content, loc):
    return {"source": name, "location": loc, "input_sha256": hashlib.sha256(content.encode()).hexdigest()[:16]}


def _pkg(g, eco, name, version, prov, spec=None, cls="observed", ntype="package"):
    nid = f"pkg:{eco}/{name}@{version}" if version else f"pkg:{eco}/{name}"
    g.add_node({"node_id": nid, "node_type": ntype, "name": name, "version": version, "ecosystem": eco,
                "class": cls, "provenance": prov, "attrs": {"version_spec": spec} if spec else {}})
    return nid


def detect(name):
    b = name.replace("\\", "/").split("/")[-1].lower()
    if b == "package.json": return "package.json"
    if b == "package-lock.json": return "package-lock.json"
    if b == "requirements.txt" or (b.startswith("requirements") and b.endswith(".txt")): return "requirements.txt"
    if b == "pyproject.toml": return "pyproject.toml"
    if b.endswith(".json"): return "service-map"
    raise InputError("UNSUPPORTED_FORMAT", f"unsupported input format: {name!r} (supported: package.json, package-lock.json, requirements.txt, pyproject.toml, *.json service map)")


def _exact(spec):
    return spec if re.fullmatch(r"\d+(\.\d+){0,3}([-+.][0-9A-Za-z.]+)?", spec or "") else None


def parse_into(g: Graph, name: str, content: str):
    if not isinstance(content, str): raise InputError("BAD_INPUT", "content must be text")
    if len(content.encode()) > MAX_INPUT_BYTES: raise InputError("INPUT_TOO_LARGE", f"{name} exceeds {MAX_INPUT_BYTES} bytes")
    kind = detect(name)
    try:
        {"package.json": _package_json, "package-lock.json": _lock, "requirements.txt": _reqs,
         "pyproject.toml": _pyproject, "service-map": _service_map}[kind](g, name, content)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as e:
        raise InputError("MALFORMED_INPUT", f"{name}: {e}")
    except (KeyError, TypeError, AttributeError) as e:
        raise InputError("MALFORMED_INPUT", f"{name}: unexpected structure ({type(e).__name__}: {e})")
    return kind


def _package_json(g, name, c):
    d = json.loads(c)
    if not isinstance(d, dict) or "name" not in d: raise InputError("MALFORMED_INPUT", f"{name}: missing 'name'")
    root = _pkg(g, "npm", d["name"], d.get("version"), _prov(name, c, "root"), ntype="application")
    for sect, kind in (("dependencies", "runtime"), ("devDependencies", "dev"), ("optionalDependencies", "optional"), ("peerDependencies", "peer")):
        for dep, spec in sorted((d.get(sect) or {}).items()):
            p = _prov(name, c, f"{sect}.{dep}")
            n = _pkg(g, "npm", dep, _exact(spec), p, spec=spec)
            g.add_edge(root, "DEPENDS_ON", n, p, "observed", f"declared in {sect}", {"dep_kind": kind})


def _lock(g, name, c):
    d = json.loads(c); pk = d.get("packages")
    if not isinstance(pk, dict): raise InputError("MALFORMED_INPUT", f"{name}: lockfileVersion 2/3 'packages' map required")
    ids = {}
    for path, info in sorted(pk.items()):
        nm = info.get("name") or (path.split("node_modules/")[-1] if path else d.get("name", "root"))
        ids[path] = _pkg(g, "npm", nm, info.get("version"), _prov(name, c, f"packages.{path or '<root>'}"),
                         ntype="application" if path == "" else "package")

    def resolve(frm, dep):
        base = frm
        while True:
            cand = (base + "/" if base else "") + "node_modules/" + dep
            if cand in pk: return cand
            if not base: return None
            i = base.rfind("/node_modules/")
            base = base[:i] if i >= 0 else ""
    for path, info in sorted(pk.items()):
        for sect, kind in (("dependencies", "runtime"), ("devDependencies", "dev"), ("optionalDependencies", "optional"), ("peerDependencies", "peer")):
            for dep in sorted(info.get(sect) or {}):
                t = resolve(path, dep)
                p = _prov(name, c, f"packages.{path or '<root>'}.{sect}.{dep}")
                if t is None:
                    g.issue("warning", "UNRESOLVED_DEP", f"{dep} (from {path or 'root'}) not in lockfile", source=name); continue
                k = "dev" if info.get("dev") and kind == "runtime" else kind
                g.add_edge(ids[path], "DEPENDS_ON", ids[t], p, "observed", f"lockfile {sect}", {"dep_kind": k})


_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")


def _pyreq(g, root, name, c, line, loc, kind):
    s = line.split(";")[0].strip()
    m = _REQ.match(s)
    if not m: g.issue("warning", "UNPARSEABLE_LINE", f"{name}:{loc}: {s!r}"); return
    pkg, spec = m.group(1).lower().replace("_", "-"), m.group(3).strip()
    ver = spec[2:].strip() if re.fullmatch(r"==\s*[0-9][^\s,*]*", spec) else None
    p = _prov(name, c, loc)
    n = _pkg(g, "pypi", pkg, ver, p, spec=spec or None)
    g.add_edge(root, "DEPENDS_ON", n, p, "observed", "declared requirement", {"dep_kind": kind})


def _reqs(g, name, c):
    root_name = name.replace("\\", "/").split("/")[-1]
    root = _pkg(g, "pypi", f"project({root_name})", None, _prov(name, c, "root"), ntype="application")
    for i, raw in enumerate(c.splitlines(), 1):
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"): continue
        if line.startswith("-"): g.issue("info", "SKIPPED_DIRECTIVE", f"{name}:{i} directive skipped: {line[:40]}"); continue
        _pyreq(g, root, name, c, line, f"line {i}", "runtime")


def _pyproject(g, name, c):
    d = tomllib.loads(c); pr = d["project"]
    root = _pkg(g, "pypi", pr["name"].lower(), pr.get("version"), _prov(name, c, "project"), ntype="application")
    for i, l in enumerate(pr.get("dependencies", [])): _pyreq(g, root, name, c, l, f"project.dependencies[{i}]", "runtime")
    for grp, ls in (pr.get("optional-dependencies") or {}).items():
        for i, l in enumerate(ls): _pyreq(g, root, name, c, l, f"optional-dependencies.{grp}[{i}]", "optional")


def _service_map(g, name, c):
    d = json.loads(c)
    if not isinstance(d, dict) or str(d.get("schema_version")) != "1" or not isinstance(d.get("nodes"), list):
        raise InputError("MALFORMED_INPUT", f"{name}: expected {{schema_version:'1', nodes:[...], edges:[...]}}")
    demo = bool(d.get("demo"))
    for i, n in enumerate(d["nodes"]):
        p = _prov(name, c, f"nodes[{i}]")
        attrs = {k: n[k] for k in ("environment", "criticality", "owner") if n.get(k)}
        if demo: attrs["demo_fixture"] = True
        g.add_node({"node_id": n["id"], "node_type": n.get("type", "unknown"), "name": n.get("name", n["id"]),
                    "version": n.get("version"), "ecosystem": n.get("ecosystem"), "class": n.get("class", "user_supplied"),
                    "provenance": p, "attrs": attrs})
    for i, e in enumerate(d.get("edges", [])):
        g.add_edge(e["source"], e["type"], e["target"], _prov(name, c, f"edges[{i}]"), e.get("class", "user_supplied"),
                   e.get("rationale", ""), {"dep_kind": e.get("dep_kind", "runtime")})


def parse_incident(raw):
    d = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(d, dict) or not d.get("affected_component") or not d.get("timestamp"):
        raise InputError("MALFORMED_INPUT", "incident needs 'timestamp' and 'affected_component'")
    try: datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00"))
    except ValueError: raise InputError("MALFORMED_INPUT", "incident timestamp must be ISO-8601")
    d.setdefault("incident_id", "inc-" + sha(d, 8)); d.setdefault("events", []); d.setdefault("advisories", []); d.setdefault("symptoms", [])
    return d


def build(files):
    """files: [{name, content}] -> (Graph, parsed_kinds). Raises InputError."""
    if not files: raise InputError("NO_INPUT", "no input files supplied")
    g, kinds = Graph(), []
    for f in files:
        kinds.append({"name": f["name"], "format": parse_into(g, f["name"], f["content"])})
    return g, kinds
