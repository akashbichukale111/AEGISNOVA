"""Dependency manifest discovery and parsing (PyPI requirements*.txt, npm package.json + package-lock.json).

Only formats with a tested parser are supported. Malformed manifests become ``issues`` (warnings), never
crashes and never guessed versions. Parsing is pure text processing: no repository code is executed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .repo import MAX_FILE_BYTES, list_files
from .untrusted import scan_text
from .versions import NPM, PYPI, is_valid, normalize_pypi_name

MAX_DEPTH = 4
_REQ_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(?:\[[^\]]*\])?\s*"
    r"(?P<spec>(?:(?:===|==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9*.+!_-]+\s*,?\s*)*)\s*(?:;.*)?$"
)
_CLAUSE = re.compile(r"(===|==|>=|<=|~=|!=|<|>)\s*([A-Za-z0-9*.+!_-]+)")
_EXACT_SEMVER = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def _dep(ecosystem, name, version, spec, relationship, manifest, kind="runtime", line=None, lockfile=None):
    return {"ecosystem": ecosystem, "name": name, "version": version, "spec": spec, "relationship": relationship,
            "manifest_path": manifest, "kind": kind, "line": line, "lockfile": lockfile}


def _strip_comment(line: str) -> str:
    return re.sub(r"(^|\s)#.*$", "", line).strip()


def parse_requirements(rel: str, text: str) -> tuple[list[dict], list[dict]]:
    deps, issues = [], []
    logical, start = [], 0
    for no, raw in enumerate(text.splitlines(), 1):
        if not logical:
            start = no
        if raw.rstrip().endswith("\\"):
            logical.append(raw.rstrip()[:-1])
            continue
        logical.append(raw)
        line = _strip_comment(" ".join(logical))
        logical = []
        if not line:
            continue
        if line.startswith("-"):
            if re.match(r"^(-r|--requirement|-c|--constraint)\b", line):
                issues.append({"path": rel, "line": start, "code": "INCLUDE_NOT_FOLLOWED", "severity": "info",
                               "message": "included requirement files are not followed; add them as separate manifests"})
            elif re.match(r"^(-e|--editable)\b", line):
                issues.append({"path": rel, "line": start, "code": "UNSUPPORTED_REQUIREMENT", "severity": "warning",
                               "message": "editable/VCS requirement ignored"})
            continue
        line = re.sub(r"\s--hash=\S+", "", line).strip()
        if "://" in line or line.startswith(("git+", "http")) or " @ " in line:
            issues.append({"path": rel, "line": start, "code": "UNSUPPORTED_REQUIREMENT", "severity": "warning",
                           "message": "direct URL/VCS requirement ignored (no version to match)"})
            continue
        m = _REQ_LINE.match(line)
        if not m:
            issues.append({"path": rel, "line": start, "code": "MALFORMED_REQUIREMENT", "severity": "warning",
                           "message": "line could not be parsed as a requirement"})
            continue
        name = normalize_pypi_name(m.group("name"))
        spec = m.group("spec").strip().rstrip(",").strip()
        clauses = _CLAUSE.findall(spec)
        version = None
        if len(clauses) == 1 and clauses[0][0] in ("==", "===") and "*" not in clauses[0][1]:
            if is_valid(PYPI, clauses[0][1]):
                version = clauses[0][1]
        kind = "dev" if "dev" in Path(rel).name.lower() or "test" in Path(rel).name.lower() else "runtime"
        deps.append(_dep(PYPI, name, version, spec or None, "unknown", rel, kind=kind, line=start))
    return deps, issues


def parse_package_json(rel: str, text: str, lock_text: str | None, lock_rel: str | None) -> tuple[list[dict], list[dict]]:
    deps, issues = [], []
    try:
        pkg = json.loads(text)
        if not isinstance(pkg, dict):
            raise ValueError("package.json root must be an object")
    except ValueError as e:
        return [], [{"path": rel, "line": None, "code": "MALFORMED_MANIFEST", "severity": "warning", "message": f"invalid JSON: {str(e)[:120]}"}]
    declared: dict[str, tuple[str, str]] = {}
    for section, kind in (("dependencies", "runtime"), ("optionalDependencies", "runtime"), ("devDependencies", "dev")):
        sec = pkg.get(section) or {}
        if not isinstance(sec, dict):
            issues.append({"path": rel, "line": None, "code": "MALFORMED_MANIFEST", "severity": "warning",
                           "message": f"{section} must be an object"})
            continue
        for name, spec in sec.items():
            if isinstance(name, str) and isinstance(spec, str):
                declared[name] = (spec, kind)
    lock_versions: dict[str, tuple[str, bool]] = {}
    if lock_text is not None:
        try:
            lock = json.loads(lock_text)
            if not isinstance(lock, dict):
                raise ValueError("lockfile root must be an object")
            packages = lock.get("packages")
            if isinstance(packages, dict):
                for key, entry in packages.items():
                    if not key or not isinstance(entry, dict) or "version" not in entry:
                        continue
                    name = entry.get("name") or key.rsplit("node_modules/", 1)[-1]
                    top = key == f"node_modules/{name}"
                    lock_versions[key] = (name, top, str(entry["version"]), bool(entry.get("dev")))
            elif isinstance(lock.get("dependencies"), dict):  # lockfile v1
                def walk(d, top=True, prefix=""):
                    for name, entry in d.items():
                        if isinstance(entry, dict) and "version" in entry:
                            lock_versions[f"{prefix}{name}"] = (name, top, str(entry["version"]), bool(entry.get("dev")))
                            if isinstance(entry.get("dependencies"), dict):
                                walk(entry["dependencies"], False, f"{prefix}{name}>")
                walk(lock["dependencies"])
        except ValueError as e:
            issues.append({"path": lock_rel, "line": None, "code": "MALFORMED_MANIFEST", "severity": "warning",
                           "message": f"invalid lockfile JSON: {str(e)[:120]}"})
            lock_versions = {}
    if lock_versions:
        for key, (name, top, version, dev) in lock_versions.items():
            rel_type = "direct" if (name in declared and top) else "transitive"
            if not is_valid(NPM, version):
                issues.append({"path": lock_rel, "line": None, "code": "UNPARSEABLE_VERSION", "severity": "warning",
                               "message": f"{name}@{version} is not a valid semver"})
                continue
            deps.append(_dep(NPM, name, version, declared.get(name, ("", ""))[0] or None, rel_type, rel,
                             kind="dev" if dev else "runtime", lockfile=lock_rel))
        locked_names = {v[0] for v in lock_versions.values()}
        for name, (spec, kind) in declared.items():
            if name not in locked_names:
                deps.append(_dep(NPM, name, None, spec, "direct", rel, kind=kind))
    else:
        for name, (spec, kind) in declared.items():
            version = spec.lstrip("v") if _EXACT_SEMVER.match(spec) else None
            deps.append(_dep(NPM, name, version, spec, "direct", rel, kind=kind))
        if declared and lock_text is None:
            issues.append({"path": rel, "line": None, "code": "NO_LOCKFILE", "severity": "info",
                           "message": "no package-lock.json: only exactly pinned versions can be matched; transitive dependencies are unknown"})
    return deps, issues


def inspect_repository(root: Path) -> dict:
    """Discover and parse manifests. Returns manifests, dependencies, issues, injection flags (no code executed)."""
    files, symlinks = list_files(root)
    by_rel = {rel: ap for rel, ap in files}
    manifests, deps, issues, flags = [], [], [], []

    def read(rel):
        ap = by_rel[rel]
        with open(ap, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
        return data.decode("utf-8", "replace")

    for rel in sorted(by_rel):
        if rel.count("/") > MAX_DEPTH:
            continue
        name = rel.rsplit("/", 1)[-1]
        if re.fullmatch(r"requirements[A-Za-z0-9._-]*\.txt", name):
            text = read(rel)
            manifests.append({"path": rel, "type": "requirements.txt", "ecosystem": PYPI})
            d, i = parse_requirements(rel, text)
            deps += d
            issues += i
            flags += scan_text(text, rel)
        elif name == "package.json":
            text = read(rel)
            base = rel[: -len("package.json")]
            lock_rel = next((base + n for n in ("package-lock.json", "npm-shrinkwrap.json") if base + n in by_rel), None)
            manifests.append({"path": rel, "type": "package.json", "ecosystem": NPM, "lockfile": lock_rel})
            lock_text = read(lock_rel) if lock_rel else None
            d, i = parse_package_json(rel, text, lock_text, lock_rel)
            deps += d
            issues += i
            flags += scan_text(text, rel)
            for other in ("yarn.lock", "pnpm-lock.yaml"):
                if base + other in by_rel:
                    issues.append({"path": base + other, "line": None, "code": "LOCKFILE_UNSUPPORTED", "severity": "info",
                                   "message": f"{other} is not parsed in this version"})
        elif re.fullmatch(r"(README|SECURITY|CONTRIBUTING|CHANGELOG)[A-Za-z0-9._-]*\.(md|txt|rst)", name, re.I) and rel.count("/") <= 1:
            flags += scan_text(read(rel)[:200_000], rel)
    return {"manifests": manifests, "dependencies": deps, "issues": issues, "injection_flags": flags[:100],
            "symlinks_skipped": symlinks}
