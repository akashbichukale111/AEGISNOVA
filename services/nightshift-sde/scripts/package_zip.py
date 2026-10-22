#!/usr/bin/env python3
"""Build and validate NightShift_SDE_Standalone.zip from an explicit allowlist (no data/, caches, tokens, .env, .git).

usage: python scripts/package_zip.py [--out PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOP = "nightshift-sde"
INCLUDE_DIRS = ["nightshift", "ui", "tests", "docs", "scripts", "fixtures"]
INCLUDE_FILES = ["README.md", "pyproject.toml", "requirements-dev.txt", ".env.example", ".gitignore"]
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv", ".git", "dist", "coverage", ".mypy_cache"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".log", ".zip", ".pem", ".key", ".p12"}
EXCLUDE_NAMES = {"local-tokens.json", ".env"}
REQUIRED = ["README.md", "pyproject.toml", "requirements-dev.txt", ".env.example", "nightshift/migrations/001_init.sql", "nightshift/server.py",
            "ui/index.html", "ui/app.js", "tests/test_api.py", "tests/test_workflow.py", "tests/test_ui_browser.py", "docs/ARCHITECTURE.md",
            "docs/API.md", "docs/SECURITY.md", "docs/ACCEPTANCE.md", "scripts/e2e_demo.py"]
SECRET_PATTERNS = [re.compile(p) for p in (r"nsd_[A-Za-z0-9_\-]{20,}", r"AKIA[0-9A-Z]{16}", r"gh[pousr]_[A-Za-z0-9]{30,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"sk-[A-Za-z0-9]{32,}", r"xox[baprs]-[A-Za-z0-9-]{20,}")]


# Documented exception: the redaction unit test contains a deliberately fake "-----BEGIN PRIVATE KEY-----\nMIIabc" stub to prove it is redacted.
ALLOW = {(f, r"-----BEGIN [A-Z ]*PRIVATE KEY-----") for f in ("nightshift-sde/tests/test_security.py", "nightshift-sde/scripts/package_zip.py", "nightshift-sde/nightshift/redact.py")}


def wanted(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    return p.is_file() and not (set(rel.parts) & EXCLUDE_PARTS) and p.suffix not in EXCLUDE_SUFFIX and p.name not in EXCLUDE_NAMES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT.parent / "NightShift_SDE_Standalone.zip"))
    out = Path(ap.parse_args().out).resolve()
    files = [ROOT / f for f in INCLUDE_FILES if (ROOT / f).exists()]
    for d in INCLUDE_DIRS:
        files += [p for p in sorted((ROOT / d).rglob("*")) if wanted(p)]
    files = [p for p in files if wanted(p)]
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, f"{TOP}/{p.relative_to(ROOT).as_posix()}")

    # ---- validation (reads the archive back; trusts nothing from the build step)
    problems = []
    if not out.exists():
        print("FAILED: zip was not created"); return 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        if bad:
            problems.append(f"corrupt member {bad}")
        names = z.namelist()
        for req in REQUIRED:
            if f"{TOP}/{req}" not in names:
                problems.append(f"missing required file {req}")
        for n in names:
            parts = set(Path(n).parts)
            if parts & EXCLUDE_PARTS or Path(n).suffix in EXCLUDE_SUFFIX or Path(n).name in EXCLUDE_NAMES or f"{TOP}/data/" in n:
                problems.append(f"forbidden file in archive: {n}")
            data = z.read(n)
            if len(data) < 2_000_000:
                text = data.decode("utf-8", "ignore")
                for pat in SECRET_PATTERNS:
                    if pat.search(text) and (n, pat.pattern) not in ALLOW:
                        problems.append(f"possible secret ({pat.pattern[:18]}…) in {n}")
        print(f"ZIP: {out}\nsize: {out.stat().st_size:,} bytes; {len(names)} files")
        tops = {}
        for n in names:
            k = "/".join(n.split("/")[1:2]) or "."
            tops[k] = tops.get(k, 0) + 1
        for k, v in sorted(tops.items()):
            print(f"  {k:<28}{v:>4} file(s)")
    if problems:
        print("VALIDATION FAILED:"); [print("  -", p) for p in problems]; return 1
    print("VALIDATION OK: required files present; no secret files/patterns, caches, data dir, or build output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
