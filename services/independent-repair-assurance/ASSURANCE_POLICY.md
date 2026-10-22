# Assurance policy
Priority order: REJECTED (identity failure, after-patch tests FAILED, CRITICAL finding) > NEEDS_HUMAN_REVIEW (no warrant) > BLOCKED (invalid warrant / runtime blocked / base mismatch) > NEEDS_HUMAN_REVIEW (tests INCONCLUSIVE, HIGH finding, auditor discrepancy) > VERIFIED only if residual risk is LOW, else VERIFIED_WITH_WARNINGS.
Because the runner is process-level only (sandbox factor = MODERATE), VERIFIED is unreachable by design in this build.
Test states: NOT_RUN, PASSED, FAILED, SKIPPED (counted), INCONCLUSIVE (timeout, zero tests), BLOCKED. A claimed "tests passed" is never trusted without executed evidence.
Risk: LOW/MODERATE/HIGH/CRITICAL/UNKNOWN; max over factors; UNKNOWN counts as HIGH-equivalent for ordering and is reported as UNKNOWN when no known factor is HIGH+. Missing evidence never lowers risk. Policy-based, not a probability.
Fail closed: missing evidence, base mismatch, unsafe/unavailable execution, integrity failure.
