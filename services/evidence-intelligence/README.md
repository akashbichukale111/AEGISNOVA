# AEGISNOVA — Evidence Intelligence (Workstream 02, standalone)
Tavily + OSV + GitHub Advisory research, source reconciliation, freshness and refresh/diff. Python 3.10+ stdlib only (no install step). Not merged into the main AEGISNOVA repo.

## Run
    python -m evidence_intel.server              # live mode, http://127.0.0.1:8080
    EI_MODE=demo python -m evidence_intel.server # fictional fixtures, labelled DEMO (try package demo-lib, PyPI, 1.1.0)
## Configure
Copy `.env.example`, export `TAVILY_API_KEY` (and optionally `GITHUB_TOKEN`) in your shell. No `.env` loader is built in; secrets are read from the process environment only.
## Test
    python -m unittest discover -s tests -v
No build or lint step exists (stdlib Python, static JS/CSS).
## Troubleshooting
Provider shows NOT_CONFIGURED → key missing. RATE_LIMITED → unauthenticated GitHub or quota; set `GITHUB_TOKEN`/wait. Empty result never means safe.
## Reset
Stop the server and delete `evidence.db`.
## Docs
ARCHITECTURE, API_AND_SCHEMAS, EVIDENCE_POLICY, THREAT_MODEL, INTEGRATION_CONTRACT, TEST_REPORT.
