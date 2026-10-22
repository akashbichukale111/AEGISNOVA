"""Evidence reconciliation: turn dependencies + provider advisories into findings.

Rules (deterministic, no model involved)
* A package is only matched when its installed version is known and parseable. Otherwise: no claim.
* A finding exists only if at least one provider's advisory range contains the installed version.
* Providers that disagree on whether the installed version is affected, or on the fix for it, produce
  ``evidence_status = conflicting`` — repair is then blocked and the conflict is shown to the human.
* Evidence older than the freshness window is ``stale`` — repair is blocked until refreshed.
* A fix version is only ever taken from advisory data; it is additionally checked against EVERY known
  advisory for the package so a "fix" that is itself affected is never proposed.
"""
from __future__ import annotations

from datetime import timedelta

from .providers import SEVERITIES, ProviderResult
from .util import iso, parse_iso, sha256_hex
from .versions import VersionParseError, compare, in_ranges, jump_kind, version_key

SEV_RANK = {s: i for i, s in enumerate(reversed(SEVERITIES))}  # UNKNOWN=0 ... CRITICAL=4


def _fix_for_installed(eco: str, version: str, ranges: list[dict]) -> str | None:
    """The `fixed` boundary of the range that contains the installed version (None if open-ended)."""
    for r in ranges:
        if in_ranges(eco, version, [r]):
            return r.get("fixed")
    return None


def _groups(adv_entries: list[dict]) -> list[list[dict]]:
    """Group advisories across providers by overlapping ids/aliases."""
    groups: list[tuple[set, list[dict]]] = []
    for a in adv_entries:
        ids = {a["id"], *a.get("aliases", [])}
        merged = None
        for g_ids, g in groups:
            if g_ids & ids:
                g_ids |= ids
                g.append(a)
                merged = (g_ids, g)
                break
        if merged is None:
            groups.append((set(ids), [a]))
    # second pass: groups bridged by a later advisory
    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if groups[i][0] & groups[j][0]:
                    groups[i][0].update(groups[j][0])
                    groups[i][1].extend(groups[j][1])
                    del groups[j]
                    changed = True
                    break
            if changed:
                break
    return [g for _, g in groups]


def finding_id(repo_id: str, ecosystem: str, package: str, advisory_ids: list[str]) -> str:
    return "fnd_" + sha256_hex("|".join([repo_id, ecosystem, package, *sorted(advisory_ids)]))[:16]


def build_findings(*, repo_id: str, dependencies: list[dict], lookups: dict, now, max_age_seconds: int,
                   provider_limitations: dict | None = None) -> dict:
    """``lookups``: {(ecosystem, package): [ProviderResult-like dicts]}. Returns findings + summary."""
    findings, unresolved, limitations_global = [], [], []
    by_pkg: dict[tuple, list[dict]] = {}
    for d in dependencies:
        by_pkg.setdefault((d["ecosystem"], d["name"]), []).append(d)
    stale_cutoff = iso(now - timedelta(seconds=max_age_seconds))

    for (eco, pkg), deps in sorted(by_pkg.items()):
        resolved = [d for d in deps if d.get("version")]
        if not resolved:
            unresolved.append({"ecosystem": eco, "package": pkg, "specs": sorted({d.get("spec") or "" for d in deps})})
            continue
        results = lookups.get((eco, pkg), [])
        if not results:
            continue
        for installed in sorted({d["version"] for d in resolved}):
            inst_deps = [d for d in resolved if d["version"] == installed]
            # flatten advisories with provider/timestamp attached
            entries = []
            for res in results:
                for adv in res["advisories"]:
                    entries.append({**adv, "_provider": res["provider"], "_mode": res["mode"], "_retrieved_at": res["retrieved_at"]})
            limitations: list = []
            affected_groups, all_ranges = [], []
            try:
                for g in _groups(entries):
                    verdicts = {}
                    for a in g:
                        verdicts.setdefault(a["_provider"], []).append(a)
                    per_provider = {}
                    for prov, advs in verdicts.items():
                        aff = any(in_ranges(eco, installed, a["ranges"]) for a in advs)
                        fixes = sorted({_fix_for_installed(eco, installed, a["ranges"]) or "∅" for a in advs if in_ranges(eco, installed, a["ranges"])})
                        per_provider[prov] = {"affected": aff, "fixes": fixes}
                    if not any(v["affected"] for v in per_provider.values()):
                        continue
                    affected_groups.append((g, per_provider))
                    all_ranges.extend(g)
            except VersionParseError as e:
                limitations_global.append({"code": "VERSION_UNPARSEABLE", "ecosystem": eco, "package": pkg,
                                           "installed": installed, "detail": str(e)[:160]})
                continue
            if not affected_groups:
                continue
            reasons: list[str] = []
            conflicts: list[dict] = []
            stale = False
            advisory_ids, evidence_refs = set(), []
            severity = "UNKNOWN"
            fix_requirements: list[str] = []
            open_ended = False
            for g, per_provider in affected_groups:
                ids = sorted({a["id"] for a in g})
                advisory_ids.update(ids)
                for a in g:
                    if SEV_RANK[a["severity"]] > SEV_RANK[severity]:
                        severity = a["severity"]
                    evidence_refs.append({"advisory_id": a["id"], "provider": a["_provider"], "mode": a["_mode"],
                                          "url": a.get("url"), "retrieved_at": a["_retrieved_at"], "summary": a["summary"]})
                    if a["_retrieved_at"] < stale_cutoff:
                        stale = True
                verdict_set = {v["affected"] for v in per_provider.values()}
                fix_sets = {tuple(v["fixes"]) for v in per_provider.values() if v["affected"]}
                if len(verdict_set) > 1:
                    conflicts.append({"advisory_ids": ids, "type": "AFFECTED_DISAGREEMENT",
                                      "providers": {p: v["affected"] for p, v in per_provider.items()}})
                if len(fix_sets) > 1:
                    conflicts.append({"advisory_ids": ids, "type": "FIX_VERSION_DISAGREEMENT",
                                      "providers": {p: v["fixes"] for p, v in per_provider.items() if v["affected"]}})
                for v in per_provider.values():
                    if v["affected"]:
                        for f in v["fixes"]:
                            if f == "∅":
                                open_ended = True
                            else:
                                fix_requirements.append(f)
            # candidate fix: smallest version >= every required fix that no known advisory still affects
            selected, candidates = None, []
            if not open_ended and fix_requirements:
                floor = max(fix_requirements, key=lambda v: version_key(eco, v))
                pool = sorted({r["fixed"] for a in entries for r in a["ranges"] if r.get("fixed")}, key=lambda v: version_key(eco, v))
                candidates = [v for v in pool if compare(eco, v, floor) >= 0]
                for v in candidates:
                    if not any(in_ranges(eco, v, a["ranges"]) for a in entries):
                        selected = v
                        break
                if selected is None:
                    reasons.append("NO_FIX_CLEARS_ALL_ADVISORIES")
            else:
                reasons.append("NO_FIX_AVAILABLE")
            if selected:
                reasons.append(f"FIX_{jump_kind(eco, installed, selected).upper()}_JUMP")
            if conflicts:
                reasons.append("EVIDENCE_CONFLICT")
            if stale:
                reasons.append("EVIDENCE_STALE")
            if severity == "UNKNOWN":
                reasons.append("SEVERITY_UNKNOWN")
            providers = {r["provider"] for r in evidence_refs}
            status = "conflicting" if conflicts else ("stale" if stale else "confirmed")
            confidence = "low" if status != "confirmed" else ("high" if len(providers) >= 2 else "medium")
            rel_set = {d["relationship"] for d in inst_deps}
            relationship = "direct" if "direct" in rel_set else ("transitive" if rel_set == {"transitive"} else "unknown")
            if not limitations and relationship == "unknown":
                limitations.append({"code": "RELATIONSHIP_UNKNOWN", "detail": "requirements files do not distinguish direct from transitive pins"})
            if len(providers) < 2:
                limitations.append({"code": "SINGLE_SOURCE", "detail": "advisory evidence comes from one provider"})
            fid = finding_id(repo_id, eco, pkg, sorted(advisory_ids))
            findings.append({
                "id": fid, "package": pkg, "ecosystem": eco, "installed_version": installed, "relationship": relationship,
                "manifest_paths": sorted({d["manifest_path"] for d in inst_deps}),
                "dependency_lines": [{"path": d["manifest_path"], "line": d.get("line"), "lockfile": d.get("lockfile"),
                                      "kind": d.get("kind")} for d in inst_deps],
                "advisory_ids": sorted(advisory_ids),
                "affected_ranges": [{"advisory_id": a["id"], "provider": a["_provider"], "ranges": a["ranges"]}
                                    for g, _ in affected_groups for a in g],
                "fixed_candidates": candidates, "selected_fix": selected, "severity": severity, "reason_codes": reasons,
                "evidence_status": status, "confidence": confidence, "limitations": limitations, "conflicts": conflicts,
                "evidence": evidence_refs,
            })
    return {"findings": findings, "unresolved": unresolved, "limitations": limitations_global}
