# Test report

Command: `python3 -m unittest discover -s tests -v`  (Python 3.12.3)
Exit code: 0

```
test_critical_production_and_weights (test_all.Blast.test_critical_production_and_weights) ... ok
test_small_noncritical_low_and_unknown_target_and_caps_warning (test_all.Blast.test_small_noncritical_low_and_unknown_target_and_caps_warning) ... ok
test_unknown_criticality_caps_at_moderate (test_all.Blast.test_unknown_criticality_caps_at_moderate) ... ok
test_immutability_hashes_and_delta (test_all.Counterfactual.test_immutability_hashes_and_delta) ... ok
test_isolate_removes_downstream (test_all.Counterfactual.test_isolate_removes_downstream) ... ok
test_not_evaluable (test_all.Counterfactual.test_not_evaluable) ... ok
test_remove_root_cause_changes_ranking_and_is_speculative (test_all.Counterfactual.test_remove_root_cause_changes_ranking_and_is_speculative) ... ok
test_upgrade_and_shift (test_all.Counterfactual.test_upgrade_and_shift) ... ok
test_export_json_markdown (test_all.ExportAndApi.test_export_json_markdown) ... ok
ok
test_malicious_names_are_data_not_markup (test_all.ExportAndApi.test_malicious_names_are_data_not_markup) ... ok
test_router_flow_and_errors (test_all.ExportAndApi.test_router_flow_and_errors) ... ok
test_cycle_not_error_and_terminates (test_all.GraphValidation.test_cycle_not_error_and_terminates) ... ok
test_disconnected (test_all.GraphValidation.test_disconnected) ... ok
test_missing_duplicate_contradictory_unsupported (test_all.GraphValidation.test_missing_duplicate_contradictory_unsupported) ... ok
test_observed_before_carries_no_impact_and_forward_edges (test_all.GraphValidation.test_observed_before_carries_no_impact_and_forward_edges) ... ok
test_traversal_direction_and_caps (test_all.GraphValidation.test_traversal_direction_and_caps) ... ok
test_direct_vs_transitive_and_dedup (test_all.Impact.test_direct_vs_transitive_and_dedup) ... ok
test_duplicate_paths_counted_once (test_all.Impact.test_duplicate_paths_counted_once) ... ok
test_exclude_dev (test_all.Impact.test_exclude_dev) ... ok
test_filters_and_unknown_fields (test_all.Impact.test_filters_and_unknown_fields) ... ok
test_lockfile_nested_resolution (test_all.Parsing.test_lockfile_nested_resolution) ... ok
test_malformed_unsupported_and_limits (test_all.Parsing.test_malformed_unsupported_and_limits) ... ok
test_package_json (test_all.Parsing.test_package_json) ... ok
test_requirements_and_pyproject (test_all.Parsing.test_requirements_and_pyproject) ... ok
test_stable_ids_and_provenance (test_all.Parsing.test_stable_ids_and_provenance) ... ok
test_competing_hypotheses_lower_confidence (test_all.RootCause.test_competing_hypotheses_lower_confidence) ... ok
test_no_evidence_is_needs_more_evidence_not_confident (test_all.RootCause.test_no_evidence_is_needs_more_evidence_not_confident) ... ok
test_old_change_outside_window_scores_lower (test_all.RootCause.test_old_change_outside_window_scores_lower) ... ok
test_ranking_status_alternatives (test_all.RootCause.test_ranking_status_alternatives) ... ok
test_temporal_contradiction (test_all.RootCause.test_temporal_contradiction) ... ok
test_unknown_component_inconclusive_and_bad_timestamp_noted (test_all.RootCause.test_unknown_component_inconclusive_and_bad_timestamp_noted) ... ok

----------------------------------------------------------------------
Ran 32 tests in 0.560s

OK
```

Lint/type/build: none configured (pure stdlib, no build step). Coverage not measured.
