# Causal analysis policy
**Principle:** a graph path is a *plausible route*, never proof. Statuses: SUPPORTED_HYPOTHESIS, PLAUSIBLE, CONTRADICTED, INCONCLUSIVE, NEEDS_MORE_EVIDENCE.
## Root-cause rule score (candidates = nodes whose impact can reach the affected component, depth<=6)
+2 path of observed/user-supplied edges only (+1 if any inferred edge); +2 if candidate is the affected component (instead of path points); +1 if <=2 hops;
+3 change/deploy event before incident inside `window_hours` (+1 outside); +2 health event before incident; +2 advisory on the component, +1 more if its version is in `affected_versions`.
Change/deploy/health event AFTER the incident is a contradiction; with no earlier evidence the status is CONTRADICTED.
Status: no evidence beyond path -> NEEDS_MORE_EVIDENCE; score>=6 SUPPORTED_HYPOTHESIS; >=3 PLAUSIBLE. Band: HIGH needs score>=8 and no contradiction; MEDIUM >=5; else LOW; lowered one band if the runner-up is within 1 point.
The band is a transparent rule indicator, NOT a calibrated probability. No percentages are shown.
## Blast radius (policy indicator, not outage/exploit probability)
Dimensions: direct, transitive, affected services, environments, criticality-weighted score (low1/medium2/high3/critical4, only for nodes with supplied criticality), shortest-path total, coverage, inferred edges, caps reached. Nodes are counted once; duplicate paths never add nodes.
Level: UNKNOWN if target absent; with criticality metadata: critical+production -> CRITICAL, critical or >=2 high -> HIGH, one high -> MODERATE, else LOW (MODERATE if >=5 services); without criticality metadata: node count alone is capped at MODERATE. Warnings for caps, inferred edges, weak or disconnected coverage (impact may be underestimated).
Production/customer-facing is never inferred from a name.
## Counterfactuals
Applied to a copy; source graph hash must be unchanged. Types: remove_node, remove_edge, isolate_node, upgrade_version (needs known version and an advisory with `affected_versions`), remove_root_cause, shift_incident. Missing data -> `NOT_EVALUABLE` with reason. Outputs list assumptions, deterministic graph consequences vs speculative causal claims, baseline/scenario hashes.
