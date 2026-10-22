"""Minimal-fix proposal builder and an independent unified-diff checker.

Supported repair: bump an exact ``name==X`` pin in requirements*.txt to the evidence-backed fixed version.
Everything else (npm, ranges, transitive pins) is reported for manual action — never auto-edited.

``build_proposal`` produces a *structured* proposal and a unified diff. ``check_diff`` re-parses ONLY the diff
text, so the independent verifier does not trust the executor's structured data.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

from .errors import PermanentError
from .repo import safe_join
from .util import canonical_json, sha256_hex
from .versions import normalize_pypi_name

_PIN = re.compile(r"^(?P<prefix>\s*)(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\s*\[[^\]]*\])?(?P<op>\s*===?\s*)(?P<ver>[A-Za-z0-9.+!_-]+)(?P<rest>.*)$")
ALLOWED_ACTIONS = ["modify_files", "run_tests_in_sandbox"]  # never merge / deploy / push


def build_proposal(root: Path, finding: dict) -> dict:
    """Build a change set from the repository tree at ``root`` (must equal the snapshot base)."""
    pkg, old, new = finding["package"], finding["installed_version"], finding["selected_fix"]
    changes, diffs = [], []
    for dl in finding["dependency_lines"]:
        path = dl["path"]
        if not path.rsplit("/", 1)[-1].startswith("requirements"):
            continue
        target = safe_join(root, path)
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        new_lines = list(lines)
        touched = False
        for i, line in enumerate(lines):
            m = _PIN.match(line.rstrip("\r\n"))
            if m and normalize_pypi_name(m.group("name")) == pkg and m.group("ver") == old:
                eol = line[len(line.rstrip("\r\n")):]
                new_line = f"{m.group('prefix')}{m.group('name')}{m.group('extras') or ''}{m.group('op')}{new}{m.group('rest')}{eol}"
                new_lines[i] = new_line
                changes.append({"path": path, "line": i + 1, "old": line.rstrip("\r\n"), "new": new_line.rstrip("\r\n")})
                touched = True
        if touched:
            diffs.append("".join(difflib.unified_diff(lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", n=1)))
    if not changes:
        raise PermanentError("NO_APPLICABLE_PIN", f"no exact pin of {pkg}=={old} found to bump")
    diff_text = "".join(diffs)
    return {
        "package": pkg, "from_version": old, "to_version": new, "finding_id": finding["id"],
        "changes": changes, "allowed_paths": sorted({c["path"] for c in changes}), "diff": diff_text,
        "diff_hash": sha256_hex(diff_text), "actions": ALLOWED_ACTIONS,
    }


def apply_proposal(workspace: Path, proposal: dict) -> None:
    """Apply the structured change set; aborts if any target line differs from what was proposed."""
    for ch in proposal["changes"]:
        if ch["path"] not in proposal["allowed_paths"]:
            raise PermanentError("PATH_NOT_ALLOWED", ch["path"])
        target = safe_join(workspace, ch["path"])
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        idx = ch["line"] - 1
        if idx >= len(lines) or lines[idx].rstrip("\r\n") != ch["old"]:
            raise PermanentError("PATCH_PRECONDITION_FAILED", f"{ch['path']}:{ch['line']} no longer matches the proposal")
        eol = lines[idx][len(lines[idx].rstrip("\r\n")):]
        lines[idx] = ch["new"] + eol
        target.write_text("".join(lines), encoding="utf-8")


def parse_unified_diff(diff: str) -> list[dict]:
    """Parse a unified diff into [{path, hunks:[{removed:[...], added:[...]}]}]. Strict: unknown lines → error."""
    files, cur, hunk = [], None, None
    for raw in diff.splitlines():
        if raw.startswith("--- "):
            cur = {"old_path": raw[4:].strip(), "new_path": None, "hunks": []}
            files.append(cur)
            hunk = None
        elif raw.startswith("+++ "):
            if cur is None:
                raise ValueError("malformed diff: +++ before ---")
            cur["new_path"] = raw[4:].strip()
        elif raw.startswith("@@"):
            if cur is None:
                raise ValueError("malformed diff: hunk before file header")
            hunk = {"removed": [], "added": []}
            cur["hunks"].append(hunk)
        elif hunk is not None and raw.startswith("-"):
            hunk["removed"].append(raw[1:])
        elif hunk is not None and raw.startswith("+"):
            hunk["added"].append(raw[1:])
        elif hunk is not None and (raw.startswith(" ") or raw == ""):
            continue
        elif raw.startswith("\\"):
            continue
        else:
            raise ValueError(f"unrecognised diff line: {raw[:40]!r}")
    return files


def check_diff(diff: str, *, package: str, from_version: str, to_version: str, allowed_paths: list[str]) -> dict:
    """Independent structural check of a diff against the claim 'only bump <package> from X to Y in allowed files'."""
    problems = []
    try:
        files = parse_unified_diff(diff)
    except ValueError as e:
        return {"ok": False, "problems": [f"DIFF_UNPARSEABLE: {e}"], "files": []}
    if not files:
        problems.append("EMPTY_DIFF")
    touched = []
    for f in files:
        path = (f["new_path"] or "").removeprefix("b/")
        old_path = (f["old_path"] or "").removeprefix("a/")
        touched.append(path)
        if path != old_path:
            problems.append(f"RENAME_NOT_ALLOWED: {old_path} -> {path}")
        if path not in allowed_paths:
            problems.append(f"PATH_NOT_ALLOWED: {path}")
        for h in f["hunks"]:
            if len(h["removed"]) != 1 or len(h["added"]) != 1:
                problems.append(f"HUNK_NOT_SINGLE_LINE: {path}")
                continue
            m_old, m_new = _PIN.match(h["removed"][0]), _PIN.match(h["added"][0])
            if not (m_old and m_new):
                problems.append(f"HUNK_NOT_A_PIN: {path}")
                continue
            if normalize_pypi_name(m_old.group("name")) != package or normalize_pypi_name(m_new.group("name")) != package:
                problems.append(f"WRONG_PACKAGE: {path}")
            if m_old.group("ver") != from_version or m_new.group("ver") != to_version:
                problems.append(f"WRONG_VERSIONS: {path}")
            strip = lambda m: (m.group("prefix"), m.group("name"), m.group("extras"), m.group("op"), m.group("rest"))
            if strip(m_old) != strip(m_new):
                problems.append(f"EXTRA_CHANGE_ON_LINE: {path}")
    return {"ok": not problems, "problems": problems, "files": sorted(set(touched))}
