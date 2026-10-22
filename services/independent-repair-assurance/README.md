# AEGISNOVA · Workstream 04 — Independent Repair Assurance (standalone)
Python 3.10+ standard library only. No install, no network, no credentials. **Not merged into the main AEGISNOVA app.**

## Run / test
    python3 -m unittest discover -s tests              # 37 unit/integration tests
    python3 -m compileall -q ira tests scripts         # syntax check (no linter bundled; no build step)
    IRA_ALLOW_LOCAL_EXEC=1 python3 -m ira serve        # UI + API at http://127.0.0.1:8765
    python3 -m ira run --patch fixtures/patches/good.diff --demo-warrant --allow-exec
    python3 -m ira run --patch fixtures/patches/good.diff            # no warrant: tests NOT_RUN, NEEDS_HUMAN_REVIEW
CLI: `run, report, breaker, risk, proof, proof-report, warrant-check, warranty check|revalidate, health, serve`.
Without `IRA_ALLOW_LOCAL_EXEC=1` runtime tests are BLOCKED (fail closed). `--demo-warrant` creates a TEST-ONLY warrant (DEMO).
Regenerate fixtures: `python3 scripts/make_fixtures.py`.

## Important limits
Execution is **process-level isolation, not a container** (temp copy, allowlisted command, filtered env, rlimits, kill-on-timeout, `unshare -rn` network namespace when available). Use only on operator-approved repos/fixtures. See SANDBOX_SECURITY.md.
## Troubleshooting / cleanup
BLOCKED tests → set IRA_ALLOW_LOCAL_EXEC=1. BASE_MISMATCH → declared base must equal the tree hash (`GET /v1/repos` or `--base-sha auto`). Cleanup: `rm -rf .data`; temp workdirs are removed automatically.
