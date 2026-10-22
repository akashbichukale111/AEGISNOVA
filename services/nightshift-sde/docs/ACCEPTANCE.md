# Feature acceptance checklist (standalone build)

Legend: ✅ implemented & automatically tested · 🟡 implemented, partially tested/limited · ⛔ not implemented / blocked

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Repository audit performed | ✅ | pre-existing backend inspected and preserved; see final report |
| 3 | Validated, persisted state transitions | ✅ | `tests/test_statemachine.py`, `tests/test_store.py` |
| 4 | Schedules + manual + webhook triggers | ✅ | `tests/test_schedule.py`, `tests/test_api.py`, `tests/test_workflow.py` |
| 5 | Idempotency / duplicate suppression | ✅ | store/schedule/api tests, `scripts/e2e_demo.py` |
| 6 | Checkpoints and resume (incl. stale base commit) | ✅ | `tests/test_workflow.py`, `tests/test_store.py` |
| 7 | Bounded retries, DLQ | ✅ | `tests/test_retry.py`, `tests/test_workflow.py` |
| 8 | Watchdog detections | ✅ | `tests/test_watchdog.py` |
| 9 | Gates not bypassable by model output | ✅ | no model exists; deterministic policy; `tests/test_security.py` |
| 10 | Isolated, resource-limited execution | 🟡 | netns + rlimits tested; **no filesystem confinement** |
| 11 | Failed tests / verifier disagreement block success | ✅ | `tests/test_workflow.py` |
| 12 | UI on real backend data, honest states | ✅ | `tests/test_ui_browser.py`, manual screenshots |
| 13 | Controls functional, authorised | ✅ | API authz tests + browser tests (viewer sees disabled controls with reasons) |
| 14 | UNWIND contract respected | 🟡 | adapter + **dev stub** only; real UNWIND not available |
| 15 | Providers accurately labelled | ✅ | Settings view, `tests/test_security.py` |
| — | GitHub API / PRs, Tavily, model provider, AWS adapters | ⛔ | not built; documented |
| — | Live OSV verification | ⛔ | adapter unit-tested with injected transport only |
