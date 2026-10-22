import json
from .graph import sha


def to_json(result):
    return json.dumps(result, indent=2, sort_keys=True, default=str)


def to_markdown(a):
    br, rc, imp = a["blast_radius"], a["root_cause"], a["impact"]
    L = [f"# Causal Impact Report `{a['analysis_id']}`", "",
         f"- Schema: {a['schema_version']}  |  Graph hash: `{a['graph_hash']}`  |  Generated: {a['generated_at']}",
         f"- Incident: **{a['incident']['incident_id']}** on `{a['incident']['affected_component']}` at {a['incident']['timestamp']}",
         f"- Impact target: `{a['impact_target']}`", "", "## Root-cause hypotheses",
         f"Overall status: **{rc.get('overall_status')}**. _{rc['caveat']}_", ""]
    for c in rc["candidates"]:
        L += [f"{c['rank']}. `{c['component_id']}` - **{c['status']}** (confidence band {c['confidence_band']}, rule score {c['score']})",
              f"   - Why: {c['confidence_rationale']}"]
        L += [f"   - Contradiction: {x}" for x in c["contradicting"]] + [f"   - Missing: {x}" for x in c["missing_evidence"]]
        L += [f"   - Next check: {c['next_diagnostic_check']}"]
    L += ["", f"## Blast radius: **{br['level']}**"] + [f"- {r}" for r in br["rationale"]]
    L += ["", "## Affected components"]
    for x in imp.get("affected", []):
        L.append(f"- `{x['node_id']}` ({x['relation']}, depth {x['depth']}, env={x['environment']}, criticality={x['criticality']})")
    L += ["", "## Known / inferred / unknown"] + [f"- Known: {x}" for x in a["known"]] + [f"- Inferred: {x}" for x in a["inferred"]] + [f"- Unknown: {x}" for x in a["unknown"]]
    L += ["", "## Limitations"] + [f"- {x}" for x in a["limitations"]]
    return "\n".join(L) + "\n"
