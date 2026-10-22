"""Deterministic root-cause hypotheses, downstream impact, blast radius and counterfactuals."""
from datetime import datetime, timezone
from . import SCHEMA_VERSION
from .graph import Graph, sha

CRIT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SERVICE_TYPES = {"service", "application"}


def _ts(s):
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _brief(e):
    return {"edge_id": e["edge_id"], "source": e["source_node_id"], "type": e["edge_type"],
            "target": e["target_node_id"], "class": e["class"], "dep_kind": e["attrs"].get("dep_kind")}


# ---------------- downstream impact ----------------
def impact(g, start, max_depth=6, max_nodes=500, environment=None, node_types=None, edge_types=None, exclude_dev=False):
    if start not in g.nodes:
        return {"status": "NOT_EVALUABLE", "reason": f"node {start!r} not in graph", "affected": []}
    info, limits = g.downstream(start, max_depth, max_nodes, edge_types, exclude_dev)
    out = []
    for nid, i in sorted(info.items(), key=lambda kv: (kv[1]["depth"], kv[0])):
        if nid == start: continue
        n = g.nodes[nid]; a = n["attrs"]
        if environment and a.get("environment") != environment: continue
        if node_types and n["node_type"] not in node_types: continue
        out.append({"node_id": nid, "name": n["name"], "node_type": n["node_type"], "depth": i["depth"],
                    "relation": "direct" if i["depth"] == 1 else "transitive", "shortest_path_count": i["n_paths"],
                    "path": [_brief(e) for e in i["path"]],
                    "why_included": f"reachable from {start} via {i['depth']} impact edge(s); a path shows plausible impact, not proof",
                    "environment": a.get("environment", "unknown"), "criticality": a.get("criticality", "unknown"),
                    "owner": a.get("owner", "unknown"), "version": n.get("version") or "unknown"})
    return {"status": "OK", "start": start, "affected": out, "limits": limits,
            "direct": [x["node_id"] for x in out if x["relation"] == "direct"],
            "transitive": [x["node_id"] for x in out if x["relation"] == "transitive"],
            "params": {"max_depth": max_depth, "max_nodes": max_nodes, "environment": environment,
                       "node_types": node_types, "edge_types": edge_types, "exclude_dev": exclude_dev}}


# ---------------- blast radius ----------------
def blast_radius(g, imp):
    if imp["status"] != "OK":
        return {"level": "UNKNOWN", "rationale": [imp.get("reason", "not evaluable")], "dimensions": {}}
    aff = imp["affected"]; cov = g.coverage()
    svcs = [a for a in aff if a["node_type"] in SERVICE_TYPES]
    crit = [a["criticality"] for a in aff if a["criticality"] in CRIT]
    envs = sorted({a["environment"] for a in aff if a["environment"] != "unknown"})
    dims = {"direct_affected": len(imp["direct"]), "transitive_affected": len(imp["transitive"]),
            "affected_services": len(svcs), "affected_environments": envs,
            "environment_unknown_count": sum(1 for a in aff if a["environment"] == "unknown"),
            "criticality_weighted_score": sum(CRIT[c] for c in crit) if crit else None,
            "criticality_known_count": len(crit), "criticality_unknown_count": len(aff) - len(crit),
            "shortest_path_total": sum(a["shortest_path_count"] for a in aff),
            "graph_observed_or_supplied_ratio": cov["observed_or_supplied_ratio"],
            "inferred_edges_on_paths": sum(1 for a in aff for e in a["path"] if e["class"] == "inferred"),
            "depth_limit_reached": imp["limits"]["depth_reached"], "node_cap_reached": imp["limits"]["node_cap_reached"]}
    why = []
    n_crit = sum(1 for c in crit if c == "critical"); n_high = sum(1 for c in crit if c == "high")
    if not aff:
        level = "LOW"; why.append("no downstream components found in the supplied graph (may be underestimated if edges are missing)")
    elif crit:
        prod = any(a["environment"] == "production" and a["criticality"] == "critical" for a in aff)
        if n_crit and prod: level = "CRITICAL"; why.append("a component with criticality=critical in environment=production is affected")
        elif n_crit or n_high >= 2: level = "HIGH"; why.append("critical component or >=2 high-criticality components affected")
        elif n_high: level = "MODERATE"; why.append("one high-criticality component affected")
        else: level = "MODERATE" if len(svcs) >= 5 else "LOW"; why.append("only low/medium criticality metadata among affected components")
    else:
        level = "MODERATE" if len(svcs) >= 5 else "LOW"
        why.append("no criticality metadata supplied: node count alone is capped at MODERATE and business impact is UNKNOWN")
    if dims["inferred_edges_on_paths"]: why.append(f"{dims['inferred_edges_on_paths']} path edge(s) are inferred, not observed")
    if dims["depth_limit_reached"] or dims["node_cap_reached"]: why.append("traversal limit reached: impact may be underestimated")
    if cov["observed_or_supplied_ratio"] < 0.5 and cov["edges"]: why.append("low observed/supplied edge ratio: coverage weak")
    if cov["components"] > 1: why.append(f"graph has {cov['components']} disconnected components: missing edges possible, impact may be underestimated")
    return {"level": level, "rationale": why, "dimensions": dims,
            "note": "Policy indicator only; not a prediction of outage or exploit probability."}


# ---------------- root cause ----------------
def root_cause(g, inc, max_depth=6, max_candidates=10):
    aff = inc["affected_component"]
    res = {"incident_id": inc["incident_id"], "affected_component": aff, "candidates": [],
           "caveat": "Reachability shows a plausible route of impact, not proof that a failure travelled along it. Confidence is a rule-based evidence indicator, not a calibrated probability."}
    if aff not in g.nodes:
        res.update(overall_status="INCONCLUSIVE", reason=f"affected component {aff!r} not in graph"); return res
    t0 = _ts(inc["timestamp"]); win = float(inc.get("window_hours", 72))
    radj = g.reverse(g.impact_adj())
    cands, limits = g.bfs(radj, aff, max_depth, 300)   # nodes whose impact can reach `aff`
    scored = []
    for nid, i in cands.items():
        n = g.nodes[nid]; score, sup, con, miss, ev = 0, [], [], [], []
        path = [_brief(e) for e in reversed(i["path"])]   # cand -> ... -> aff
        if nid == aff: score += 2; sup.append("incident is on this component itself")
        elif all(e["class"] != "inferred" for e in i["path"]): score += 2; sup.append("path to symptom uses only observed/user-supplied edges")
        else: score += 1; sup.append("path to symptom includes inferred edges (weaker)")
        if i["depth"] <= 2: score += 1; sup.append("short dependency path (<=2 hops)")
        before = after = False
        for ev_ in inc["events"]:
            if ev_.get("component") != nid: continue
            et = ev_.get("type", "unknown"); eid = ev_.get("event_id", sha(ev_, 6))
            try: dt = (t0 - _ts(ev_["timestamp"])).total_seconds() / 3600
            except (KeyError, ValueError): miss.append(f"event {eid} has no valid timestamp"); continue
            ev.append(eid)
            if dt < 0:
                if et in ("change", "deploy", "health"):
                    after = True; con.append(f"{et} event {eid} occurred AFTER the incident ({-dt:.1f}h later): cannot be its cause")
            elif et in ("change", "deploy"):
                before = True; pts = 3 if dt <= win else 1; score += pts
                sup.append(f"{et} event {eid} {dt:.1f}h before incident ({'inside' if dt <= win else 'outside'} {win:g}h window)")
            elif et == "health":
                before = True; score += 2; sup.append(f"health event {eid} {dt:.1f}h before incident")
        for adv in inc["advisories"]:
            if adv.get("component") != nid: continue
            ev.append(adv.get("id", "advisory")); score += 2; sup.append(f"advisory {adv.get('id')} references this component")
            av = adv.get("affected_versions")
            if av and n.get("version"):
                if n["version"] in av: score += 1; sup.append(f"version {n['version']} is listed as affected")
                else: con.append(f"version {n['version']} is NOT in advisory affected_versions")
            elif av: miss.append("component version unknown: cannot match advisory")
        if not ev: miss.append("no change/health/advisory evidence supplied for this component")
        evidence_score = score - (2 if nid == aff or all(e["class"] != "inferred" for e in i["path"]) else 1) - (1 if i["depth"] <= 2 else 0)
        if after and not before: status = "CONTRADICTED"
        elif evidence_score == 0: status = "NEEDS_MORE_EVIDENCE"
        elif score >= 6: status = "SUPPORTED_HYPOTHESIS"
        elif score >= 3: status = "PLAUSIBLE"
        else: status = "NEEDS_MORE_EVIDENCE"
        conf = "HIGH" if score >= 8 and not con else "MEDIUM" if score >= 5 else "LOW"
        nxt = ("Compare the change/deploy diff on this component against symptoms; roll back in staging and see whether the symptom disappears"
               if any("change" in s or "deploy" in s for s in sup) else
               "Check whether the advisory's vulnerable code path is reachable in the affected component"
               if any("advisory" in s for s in sup) else
               "Collect change, deploy and health telemetry for this component in the incident window")
        scored.append({"component_id": nid, "name": n["name"], "status": status, "confidence_band": conf, "score": score,
                       "confidence_rationale": f"rule score {score}: " + "; ".join(sup or ["no supporting rules fired"]),
                       "supporting": sup, "contradicting": con, "evidence_ids": sorted(set(ev)),
                       "provenance": n["provenance"], "path_to_symptom": path, "assumptions": [
                           "edge declarations are complete and correct", "event timestamps share one clock/timezone"],
                       "missing_evidence": miss, "next_diagnostic_check": nxt})
    scored.sort(key=lambda c: (-c["score"], c["component_id"]))
    for k, c in enumerate(scored):
        c["rank"] = k + 1
        c["alternatives"] = [x["component_id"] for x in scored[:max_candidates] if x is not c][:3]
    if len(scored) > 1 and scored[0]["score"] >= 3 and scored[0]["score"] - scored[1]["score"] <= 1:
        scored[0]["confidence_band"] = "LOW" if scored[0]["confidence_band"] == "MEDIUM" else scored[0]["confidence_band"]
        scored[0]["missing_evidence"].append(f"competing hypothesis {scored[1]['component_id']} scores within 1 point")
    res["candidates"] = scored[:max_candidates]
    res["limits"] = limits
    top = scored[0]["status"] if scored else "INCONCLUSIVE"
    res["overall_status"] = top if top in ("SUPPORTED_HYPOTHESIS", "PLAUSIBLE") else ("NEEDS_MORE_EVIDENCE" if scored else "INCONCLUSIVE")
    return res


# ---------------- full analysis ----------------
def analyze(g, inc, target=None, **kw):
    rca = root_cause(g, inc)
    tgt = target or (rca["candidates"][0]["component_id"] if rca["candidates"] and rca["candidates"][0]["status"] in ("SUPPORTED_HYPOTHESIS", "PLAUSIBLE") else inc["affected_component"])
    imp = impact(g, tgt, **kw); br = blast_radius(g, imp); cov = g.coverage()
    known = [f"{cov['nodes']} nodes / {cov['edges']} edges loaded", f"{cov['edge_classes']['observed']} observed and {cov['edge_classes']['user_supplied']} user-supplied edges"]
    inferred = [f"{cov['edge_classes']['inferred']} inferred edges (not independently verified)"] if cov["edge_classes"]["inferred"] else []
    unknown = [f"{cov['packages_with_unknown_version']} packages with unknown exact version",
               f"{cov['nodes_with_unknown_criticality']} nodes with unknown criticality", "runtime reachability of dependency paths"]
    warn = [m for m in br["rationale"] if "limit" in m or "coverage" in m or "disconnected" in m]
    body = {"schema_version": SCHEMA_VERSION, "graph_hash": g.hash(), "incident": inc, "impact_target": tgt,
            "root_cause": rca, "impact": imp, "blast_radius": br, "graph_coverage": cov,
            "known": known, "inferred": inferred, "unknown": unknown, "warnings": warn,
            "recommended_next_steps": [c["next_diagnostic_check"] for c in rca["candidates"][:3]],
            "limitations": ["Analysis is only as complete as the supplied inputs", "Graph reachability is not causation",
                            "Blast radius is a policy indicator, not a probability"]}
    body["analysis_id"] = "an-" + sha([body["graph_hash"], inc["incident_id"], tgt], 12)
    body["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return body


# ---------------- counterfactuals ----------------
def counterfactual(g, inc, scenario, **kw):
    """Apply a hypothetical change to a COPY. Source graph and incident are never mutated."""
    base_hash = g.hash(); typ = scenario.get("type"); sg, si = g.copy(), _deep(inc)
    assumptions, spec, nev = ["Scenario is hypothetical, not a prediction of real-world behaviour"], [], None
    if typ == "remove_node":
        t = scenario.get("node_id")
        if t not in sg.nodes: nev = f"node {t!r} not in graph"
        else:
            del sg.nodes[t]; sg.edges = {k: e for k, e in sg.edges.items() if t not in (e["source_node_id"], e["target_node_id"])}
            assumptions.append(f"{t} and all its edges are removed; dependents are assumed not to rewire elsewhere")
            if t == inc["affected_component"]: nev = "cannot remove the incident's affected component"
    elif typ == "remove_edge":
        eid = scenario.get("edge_id")
        if eid not in sg.edges: nev = f"edge {eid!r} not in graph"
        else: del sg.edges[eid]; assumptions.append("the edge never existed (e.g. proposed/inferred dependency is false)")
    elif typ == "isolate_node":
        t = scenario.get("node_id")
        if t not in sg.nodes: nev = f"node {t!r} not in graph"
        else:
            sg.edges = {k: e for k, e in sg.edges.items() if t not in (e["source_node_id"], e["target_node_id"])}
            assumptions.append(f"{t} is kept but isolated from every neighbour")
    elif typ == "upgrade_version":
        t, nv = scenario.get("node_id"), scenario.get("new_version")
        advs = [a for a in inc["advisories"] if a.get("component") == t and a.get("affected_versions")]
        if t not in sg.nodes or not nv: nev = "node_id and new_version required and node must exist"
        elif not sg.nodes[t].get("version"): nev = "current version unknown: cannot reason about upgrade"
        elif not advs: nev = "no advisory with affected_versions for this node: topology effect of an upgrade is unknowable from the supplied data"
        else:
            sg.nodes[t]["version"] = nv
            si["advisories"] = [a for a in si["advisories"] if not (a.get("component") == t and nv not in a["affected_versions"])]
            assumptions.append(f"advisory affected_versions lists are authoritative; dependencies of {t}@{nv} assumed unchanged")
            spec.append("whether the upgrade fixes the real incident is a speculative causal hypothesis")
    elif typ == "remove_root_cause":
        t = scenario.get("node_id")
        if t not in sg.nodes: nev = f"node {t!r} not in graph"
        else:
            si["events"] = [e for e in si["events"] if e.get("component") != t]; si["advisories"] = [a for a in si["advisories"] if a.get("component") != t]
            assumptions.append(f"all supplied evidence on {t} is treated as absent")
            spec.append("whether the incident would still have occurred is NOT determined by the graph")
    elif typ == "shift_incident":
        t = scenario.get("node_id"); ts = scenario.get("timestamp")
        if t not in sg.nodes: nev = f"node {t!r} not in graph"
        else:
            si["affected_component"] = t
            if ts:
                try: _ts(ts); si["timestamp"] = ts
                except ValueError: nev = "invalid timestamp"
            assumptions.append("symptoms are re-attributed to the new component/time unchanged")
    else:
        nev = f"unknown scenario type {typ!r}"
    assert g.hash() == base_hash
    sc_hash = sha([base_hash, scenario], 16)
    if nev:
        return {"status": "NOT_EVALUABLE", "reason": nev, "scenario": scenario, "scenario_hash": sc_hash, "baseline_graph_hash": base_hash}
    base = analyze(g, inc, **kw)
    tgt = base["impact_target"] if base["impact_target"] in sg.nodes else si["affected_component"]
    if typ == "shift_incident": tgt = si["affected_component"]
    scen = analyze(sg, si, target=tgt, **kw)
    a0 = {a["node_id"] for a in base["impact"]["affected"]}; a1 = {a["node_id"] for a in scen["impact"].get("affected", [])}
    r0 = {c["component_id"]: c["status"] for c in base["root_cause"]["candidates"]}
    r1 = {c["component_id"]: c["status"] for c in scen["root_cause"]["candidates"]}
    delta = {"affected_removed": sorted(a0 - a1), "affected_added": sorted(a1 - a0),
             "blast_level": [base["blast_radius"]["level"], scen["blast_radius"]["level"]],
             "root_cause_top": [(base["root_cause"]["candidates"] or [{}])[0].get("component_id"), (scen["root_cause"]["candidates"] or [{}])[0].get("component_id")],
             "hypothesis_status_changes": {k: [r0.get(k), r1.get(k)] for k in sorted(set(r0) | set(r1)) if r0.get(k) != r1.get(k)}}
    return {"status": "OK", "scenario": scenario, "scenario_hash": sc_hash, "baseline_graph_hash": base_hash,
            "scenario_graph_hash": sg.hash(), "baseline": _summ(base), "scenario_result": _summ(scen), "delta": delta,
            "assumptions": assumptions,
            "deterministic_consequences": ["Affected set, paths, blast level and hypothesis ranking recomputed on the modified graph copy"],
            "speculative": spec or ["Any claim that the real incident would change is speculative"],
            "evidence_gaps": scen["unknown"]}


def _deep(x):
    import copy; return copy.deepcopy(x)


def _summ(a):
    return {"impact_target": a["impact_target"], "affected": [x["node_id"] for x in a["impact"].get("affected", [])],
            "blast_level": a["blast_radius"]["level"], "overall_rca_status": a["root_cause"].get("overall_status"),
            "top_candidates": [(c["component_id"], c["status"], c["score"]) for c in a["root_cause"]["candidates"][:3]]}
