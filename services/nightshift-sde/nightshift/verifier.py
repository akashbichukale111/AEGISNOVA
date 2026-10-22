"""Independent verification of a proposed repair.

The verifier does NOT consume the executor's structured proposal as truth. It re-derives the change from the
filesystem (original tree vs patched workspace), re-parses the resulting diff with a strict parser, re-runs the
dependency inspection on the patched tree against the stored advisory evidence, and compares everything to the claim.
Any disagreement blocks the repair result. (In AEGISNOVA proper this role is played by Independent Repair Assurance;
this is the standalone deterministic stand-in and is labelled as such everywhere.)
"""
from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path

from .evidence import build_findings
from .manifests import inspect_repository
from .repair import check_diff
from .repo import list_files
from .util import sha256_hex

VERIFIER_LABEL = "built-in deterministic verifier (not AEGISNOVA Independent Repair Assurance)"


def _read_map(root: Path) -> dict[str, bytes]:
    files, _ = list_files(root)
    out = {}
    for rel, ap in files:
        if rel.startswith(".nightshift-home/"):
            continue
        with open(ap, "rb") as fh:
            out[rel] = fh.read()
    return out


def independent_diff(base: Path, patched: Path) -> tuple[str, list[str]]:
    a, b = _read_map(base), _read_map(patched)
    changed = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))
    parts = []
    for p in changed:
        old = a.get(p, b"").decode("utf-8", "replace").splitlines(keepends=True)
        new = b.get(p, b"").decode("utf-8", "replace").splitlines(keepends=True)
        parts.append("".join(difflib.unified_diff(old, new, fromfile=f"a/{p}", tofile=f"b/{p}", n=1)))
    return "".join(parts), changed


def verify(*, base: Path, patched: Path, proposal: dict, finding: dict, lookups: dict, now: datetime, max_age_seconds: int,
           repo_id: str, original_finding_ids: list[str], tests: dict) -> dict:
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})

    diff, changed = independent_diff(base, patched)
    add("changed_paths_match_proposal", changed == sorted(proposal["allowed_paths"]), f"changed={changed} proposed={sorted(proposal['allowed_paths'])}")
    d = check_diff(diff, package=finding["package"], from_version=finding["installed_version"], to_version=proposal["to_version"],
                   allowed_paths=list(proposal["allowed_paths"]))
    add("diff_only_bumps_target_pin", d["ok"], "; ".join(d["problems"]) or "single-line pin bump(s) only")
    ind_hash = sha256_hex(diff)
    add("independent_diff_hash_matches", ind_hash == proposal["diff_hash"], f"independent={ind_hash[:12]} proposal={proposal['diff_hash'][:12]}")
    add("fix_is_evidence_backed", proposal["to_version"] == finding.get("selected_fix") and proposal["to_version"] in finding.get("fixed_candidates", []),
        f"selected={finding.get('selected_fix')} candidates={finding.get('fixed_candidates')}")
    add("baseline_tests_passed", tests.get("baseline", {}).get("exit_code") == 0, f"exit={tests.get('baseline', {}).get('exit_code')}")
    add("patched_tests_passed", tests.get("patched", {}).get("exit_code") == 0 and not tests.get("patched", {}).get("timed_out"),
        f"exit={tests.get('patched', {}).get('exit_code')}")
    # re-inspect the patched tree and re-match against the stored evidence
    try:
        insp = inspect_repository(patched)
        res = build_findings(repo_id=repo_id, dependencies=insp["dependencies"], lookups=lookups, now=now, max_age_seconds=max_age_seconds)
        after_ids = {f["id"] for f in res["findings"]}
        add("target_finding_resolved", finding["id"] not in after_ids and not any(
            f["package"] == finding["package"] and f["ecosystem"] == finding["ecosystem"] for f in res["findings"]),
            "patched tree no longer matches the advisory evidence for the package")
        new_ids = sorted(after_ids - set(original_finding_ids))
        add("no_new_findings_introduced", not new_ids, f"new={new_ids}")
        installed = {d_["version"] for d_ in insp["dependencies"] if d_["name"] == finding["package"] and d_["ecosystem"] == finding["ecosystem"]}
        add("patched_version_is_target", installed == {proposal["to_version"]}, f"installed={sorted(v for v in installed if v)}")
    except Exception as e:  # noqa: BLE001 — a verifier crash is a disagreement, never a pass
        add("reinspection_succeeded", False, f"{type(e).__name__}: {e}")
    ok = all(c["ok"] for c in checks)
    return {"verdict": "agree" if ok else "disagree", "verifier": VERIFIER_LABEL, "checks": checks,
            "independent_diff_hash": ind_hash, "changed_paths": changed}
