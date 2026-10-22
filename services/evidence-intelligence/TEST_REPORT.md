# Test report

Command: `python -m unittest discover -s tests -v` (Python 3.12.3)

```
test_aliases_grouped_and_mirror_not_independent (test_core.T.test_aliases_grouped_and_mirror_not_independent) ... ok
test_applicability (test_core.T.test_applicability) ... ok
test_bundle_provenance_citations_hash (test_core.T.test_bundle_provenance_citations_hash) ... ok
test_conflicts_preserved (test_core.T.test_conflicts_preserved) ... ok
test_empty_never_safe (test_core.T.test_empty_never_safe) ... ok
test_export_and_evidence_lookup (test_core.T.test_export_and_evidence_lookup) ... ok
test_freshness_thresholds_and_dates (test_core.T.test_freshness_thresholds_and_dates) ... ok
test_http_end_to_end (test_core.T.test_http_end_to_end) ... /usr/lib/python3.12/unittest/case.py:589: ResourceWarning: unclosed <socket.socket fd=3, family=2, type=1, proto=0, laddr=('127.0.0.1', 46331)>
  if method() is not None:
ResourceWarning: Enable tracemalloc to get the object allocation traceback
ok
test_missing_credentials_partial (test_core.T.test_missing_credentials_partial) ... ok
test_provider_failures (test_core.T.test_provider_failures) ... ok
test_redaction_and_untrusted (test_core.T.test_redaction_and_untrusted) ... ok
test_refresh_unchanged_changed_unavailable (test_core.T.test_refresh_unchanged_changed_unavailable) ... ok
test_uncomparable (test_core.T.test_uncomparable) ... ok
test_validation (test_core.T.test_validation) ... ok

----------------------------------------------------------------------
Ran 14 tests in 0.585s

OK
```

Not run: lint/type-check/build (none configured). Live provider calls: NOT verified (sandbox DNS/network blocked: curl to api.osv.dev failed with exit 6, could not resolve host); all provider tests use fictional fixtures against the real adapter code. Request/response shapes follow the public OSV, GitHub Advisories REST and Tavily Search docs as recalled, not re-fetched here. UI verified via served static files and API tests only, not in a real browser.
