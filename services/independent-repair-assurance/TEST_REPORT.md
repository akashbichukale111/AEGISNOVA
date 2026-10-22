# TEST REPORT (actual results, generated 2026-10-20T05:24:22Z)

Environment: Python 3.12.3, Linux container, `unshare -rn` network isolation available: yes (health reports it).

## python3 -m unittest discover -s tests -v
```
Ran 37 tests in 2.530s
OK
```

## python3 -m compileall -q ira tests scripts
exit code 0 (syntax only). No linter/type-checker/build step exists in this project: NOT_RUN.

## Covered
- test_allowlist (test_ira.TestRunner.test_allowlist) ... ok
- test_inconclusive_when_no_tests (test_ira.TestRunner.test_inconclusive_when_no_tests) ... ok
- test_redaction_and_env_filter (test_ira.TestRunner.test_redaction_and_env_filter) ... ok
- test_timeout_and_kill (test_ira.TestRunner.test_timeout_and_kill) ... ok
- test_action (test_ira.TestWarrant.test_action) ... ok
- test_changed_patch (test_ira.TestWarrant.test_changed_patch) ... ok
- test_expired (test_ira.TestWarrant.test_expired) ... ok
- test_malformed (test_ira.TestWarrant.test_malformed) ... ok
- test_missing (test_ira.TestWarrant.test_missing) ... ok
- test_overbroad (test_ira.TestWarrant.test_overbroad) ... ok
- test_revoked (test_ira.TestWarrant.test_revoked) ... ok
- test_scope (test_ira.TestWarrant.test_scope) ... ok
- test_tamper (test_ira.TestWarrant.test_tamper) ... ok
- test_valid (test_ira.TestWarrant.test_valid) ... ok

## Not tested / not executed
- Real container sandbox (unavailable); hostile-code containment.
- Browser UI (no browser automation here; only HTTP 200 for / and API tests).
- Non-Python ecosystems; unpublished JSON Schemas.
- ZIP extraction test result is reported in the session's final report, not embedded (would be self-referential).
