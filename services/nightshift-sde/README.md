# NightShift SDE — standalone build

Internal autonomous repository-engineering engine of **AEGISNOVA — A New Standard for Safe AI**.
Durable scheduling, jobs, checkpoints, leases, retries, watchdog recovery, scoped approvals, sandboxed verified repairs, and a premium operations console.

> **Status: standalone, NOT merged into the main AEGISNOVA app.** Integrations with UNWIND, Independent Repair Assurance, GitHub API, Tavily, model providers and AWS are **not connected** (see *Integration status*). Nothing in the UI is fabricated: with an empty database it shows empty states.

## Requirements
Python ≥ 3.11 (standard library only at runtime), Linux recommended (sandbox uses `unshare`). `pytest` for tests. Optional: Playwright + Chromium for the browser tests.

## Install & run (local mode, no cloud, no credentials)
```bash
cd nightshift-sde
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt   # only pytest is needed
cp .env.example .env            # optional; defaults work. Never commit real values.
python -m nightshift init        # creates ./data, applies migrations, writes 0600 local dev tokens
python -m nightshift seed-demo   # OPTIONAL: registers 5 synthetic demo repos + advisory snapshots (no fake history)
python -m nightshift serve       # API + console + scheduler + watchdog + 1 worker  → http://127.0.0.1:8787/
python -m nightshift token admin # print a token to sign in (roles: viewer, operator, approver, admin)
```
Other commands: `worker` (extra worker process on the same DB), `tick` (one scheduler+watchdog tick), `migrate`, `migrate-down --yes` (destructive), `verify-audit`.

## Demonstration (≈2 minutes)
With the server running and demo data seeded:
```bash
python scripts/e2e_demo.py
```
It runs, through the real HTTP API: (1) a read-only inspection → `investigation_only`; (2) an idempotent re-trigger; (3) a write-capable run → scoped approval requested → **self-approval refused** → independent approval → sandboxed patch + baseline/patched tests + verifier → Repair Proof (`repair_verified`, *not applied or merged*); (4) a repo whose evidence conflicts → repair correctly **not** performed; finally verifies the audit hash chain. Then open the console and follow the job in **Jobs → job → Observatory**.

Console routes: Command Center `#/`, Jobs `#/jobs`, Job Observatory `#/jobs/<id>`, Schedule Studio `#/schedules`, Repository Fleet `#/fleet`, Dependency Intelligence `#/dependencies`, Recovery & Reliability `#/recovery`, Evidence & Audit `#/audit`, Settings & Providers `#/settings`.

## Test
```bash
python -m pytest -q                       # backend + static UI checks (+ browser tests if Playwright is installed)
pip install playwright && python -m playwright install chromium   # optional, for tests/test_ui_browser.py
NIGHTSHIFT_TEST_CHROMIUM=/path/to/chromium python -m pytest tests/test_ui_browser.py -q
```
Backend tests use synthetic **test-data** fixtures and a deterministic fake clock. Fixture repositories under `fixtures/demo-repos/` are synthetic and contain their own tests, which run only inside the sandbox (hence `testpaths = tests`).

## Package
`python scripts/package_zip.py` builds `NightShift_SDE_Standalone.zip` (next to the project folder), then validates it (contents, required files, secret scan) and prints path and size.

## Configuration
See `.env.example` (all `NIGHTSHIFT_*`). Tokens come from the 0600 file in the data dir or `NIGHTSHIFT_<ROLE>_TOKEN`. Secrets are never displayed.

## Integration status
| Capability | Status |
|---|---|
| Scheduler, jobs, state machine, checkpoints/resume, leases + fencing, retries/DLQ, watchdog, audit chain | **Implemented and tested** (local SQLite) |
| Dependency inspection: `requirements.txt`, `package.json`/`package-lock.json` | Implemented and tested; other ecosystems **not** supported |
| Advisories: local snapshot files | Implemented (synthetic demo data). OSV live: implemented, **off by default, not verified against the live API in this session** |
| Sandboxed repair + tests + built-in verifier + Repair Proof | Implemented and tested (Python `unittest` repos); **no filesystem confinement** |
| GitHub webhook intake (HMAC, dedupe) | Implemented and tested; **no GitHub API client** → no branches, no PRs |
| UNWIND governance | **Dev stub** behind an adapter (`governance.py`), labelled everywhere |
| AEGISNOVA Independent Repair Assurance | **Not connected** (built-in deterministic verifier) |
| Tavily, NVIDIA/Nebius model provider | **Not implemented**; no model is used |
| AWS (EventBridge, Step Functions, SQS, SNS, S3, …) | **Design only** (`docs/AWS.md`) |
| Notifications | Local outbox (not external delivery); generic webhook optional; email/SMS/WhatsApp not implemented |

## Troubleshooting
* *401 in the console* — token wrong/rotated: `python -m nightshift token admin`.
* *Repairs fail with sandbox blocked* — the host forbids `unshare -rn`. Run in a container that allows user namespaces, or (dev only) `NIGHTSHIFT_SANDBOX_REQUIRE_NETNS=0` (network then **not** isolated).
* *Port in use* — `NIGHTSHIFT_PORT=8790`.
* *“database is locked”* — only one process group per data dir is supported besides extra `worker` processes.
* *Timezone rejected* — use IANA names (`Asia/Kolkata`, not `Asia/Calcutta`).

## Cleanup
Stop the server (Ctrl-C), then `rm -rf data/ .venv/ .pytest_cache/`. Demo repos live under `data/repos/demo/`.

## Docs
`docs/ARCHITECTURE.md`, `docs/API.md`, `docs/SECURITY.md`, `docs/AWS.md`, `docs/ACCEPTANCE.md`.
