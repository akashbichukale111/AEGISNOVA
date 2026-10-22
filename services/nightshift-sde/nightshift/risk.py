"""Deterministic risk scoring and repair-eligibility policy.

Nothing here is model-driven. Inputs are structured findings + a versioned policy + job/repo context;
outputs are a score, a tier, reason codes and a repair decision. A model can never alter any of this.
"""
from __future__ import annotations

from .evidence import SEV_RANK

SEV_BASE = {"CRITICAL": 90, "HIGH": 70, "MEDIUM": 45, "LOW": 20, "UNKNOWN": 35}
TIERS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def tier_for(score: int) -> str:
    if score >= 85:
        return "CRITICAL"
    if score >= 65:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def score_finding(f: dict) -> tuple[int, str, list[str]]:
    score = SEV_BASE.get(f["severity"], 35)
    reasons = [f"SEVERITY_{f['severity']}"]
    if f["relationship"] == "direct":
        score += 5
        reasons.append("DIRECT_DEPENDENCY")
    if f["selected_fix"] is None:
        score += 10
        reasons.append("NO_REMEDIATION_AVAILABLE")
    if f["evidence_status"] == "conflicting":
        score += 5
        reasons.append("EVIDENCE_CONFLICT")
    if f["evidence_status"] == "stale":
        score += 5
        reasons.append("EVIDENCE_STALE")
    score = max(0, min(100, score))
    return score, tier_for(score), reasons


def repair_blockers(f: dict, *, allow_repair: bool, policy_body: dict, test_command_key: str) -> list[str]:
    """Ordered list of reasons a repair of this finding is NOT justified. Empty list == eligible."""
    blockers = []
    if not allow_repair:
        blockers.append("REPAIR_NOT_AUTHORIZED")
    if f["ecosystem"] != "PyPI":
        blockers.append("UNSUPPORTED_REPAIR_ECOSYSTEM")
    if f["evidence_status"] == "conflicting":
        blockers.append("EVIDENCE_CONFLICT")
    if f["evidence_status"] == "stale":
        blockers.append("EVIDENCE_STALE")
    if f["selected_fix"] is None:
        blockers.append("NO_FIX_AVAILABLE")
    pinned = [d for d in f.get("dependency_lines", []) if d["path"].rsplit("/", 1)[-1].startswith("requirements")]
    if f["ecosystem"] == "PyPI" and not pinned:
        blockers.append("NOT_A_DIRECT_PIN")
    if f["selected_fix"] and "FIX_MAJOR_JUMP" in f["reason_codes"] and not policy_body.get("allow_major_jump", False):
        blockers.append("MAJOR_VERSION_JUMP")
    if test_command_key == "none":
        blockers.append("NO_REGRESSION_GATE")
    min_sev = policy_body.get("min_severity_for_repair", "LOW")
    if SEV_RANK.get(f["severity"], 0) < SEV_RANK.get(min_sev, 0):
        blockers.append("SEVERITY_BELOW_POLICY_MINIMUM")
    return blockers


def assess(findings: list[dict], *, allow_repair: bool, policy: dict, test_command_key: str) -> dict:
    body = policy["body"]
    per = []
    for f in findings:
        score, tier, reasons = score_finding(f)
        blockers = repair_blockers(f, allow_repair=allow_repair, policy_body=body, test_command_key=test_command_key)
        per.append({"finding_id": f["id"], "package": f["package"], "score": score, "tier": tier, "reason_codes": reasons,
                    "repair_blockers": blockers, "eligible": not blockers})
    if not per:
        return {"score": 0, "tier": "LOW", "reason_codes": ["NO_FINDINGS"], "repair_decision": "NO_FINDINGS",
                "per_finding": [], "candidate": None, "policy": {"name": policy["name"], "version": policy["version"]},
                "approval_required": False, "blockers": []}
    top = max(per, key=lambda p: (p["score"], p["package"]))
    eligible = sorted([p for p in per if p["eligible"]], key=lambda p: (-p["score"], p["package"]))
    reason_codes = sorted({r for p in per for r in p["reason_codes"]})
    candidate = eligible[0] if eligible else None
    if candidate:
        approval_required = candidate["tier"] in body.get("approval_required_tiers", list(TIERS))
        decision = "REPAIR_PROPOSED_REQUIRES_APPROVAL" if approval_required else "REPAIR_PROPOSED_NO_APPROVAL_REQUIRED"
    else:
        approval_required = False
        decision = "INVESTIGATION_ONLY"
    blockers = sorted({b for p in per if not p["eligible"] for b in p["repair_blockers"]}) if not candidate else []
    return {"score": top["score"], "tier": top["tier"], "reason_codes": reason_codes, "repair_decision": decision,
            "per_finding": per, "candidate": candidate, "policy": {"name": policy["name"], "version": policy["version"]},
            "approval_required": approval_required, "blockers": blockers}
