# AEGISNOVA - Autonomous Operations & Notifications (Workstream 05, standalone)

*A New Standard for Safe AI.* A local-first operations control plane: define/start/inspect/pause/resume/cancel/retry workflows, wait durably for governance approval (UNWIND boundary), send notifications through adapters, track provider acceptance vs delivery, retry and dead-letter, and surface health/alarms.

**Status: development build, not production-ready.** Nothing was deployed; no cloud resources were created. See "Honest status" below.

## Requirements
Python 3.10+ (tested 3.12) - standard library only. Node 18+ is needed only for the UI render tests. `boto3` is optional and only used when you explicitly enable AWS.

## Run locally
```
python3 -m aegisnova_ops            # http://127.0.0.1:8080
cat .local/dev-tokens.json          # viewer / operator / admin dev tokens (created on first start, mode 0600)
```
Open the URL, paste the **admin** token in the sidebar ("Use token"), then Workflow Runs → *Start sample workflow* (approval required). Approval Inbox → *Grant (dev)* (a clearly labelled TEST decision) → the run resumes and completes; Notifications shows the LOCAL-sink attempt. Restart the process mid-wait: the run stays `WAITING_FOR_APPROVAL` and resumes after the decision.

Config is via environment variables (see `.env.example`; the app does not auto-load `.env`: `set -a; . ./.env; set +a`). With no variables it runs fully offline in LOCAL mode.

## Tests
```
./run_tests.sh
# or: python3 -m unittest discover -s tests -v   and   node --test tests/ui/render.test.js
```
Default tests need no credentials and make no network calls (fake clients only). Results: `docs/TEST_REPORT.md`.

## Layout
```
aegisnova_ops/   engine, store, contracts, governance, providers, aws adapters, observability, app (HTTP), static UI
infra/           template.yaml (SAM/CloudFormation, not deployed), state_machine.asl.json
tests/           Python unittest suites + tests/ui (node:test)
docs/            architecture, state machine, governance, notification policy, AWS guides, runbooks, API, integration, threat model, audit, test report
```

## Screens
Operations Overview · Workflow Runs (+detail timeline) · Approval Inbox · Notifications (+detail/replay) · Queues & Dead Letters (+DLQ detail, dry-run/confirmed redrive) · Reliability & Alerts · Event Log · Settings/Integrations (read-only tests). Environment badge shows LOCAL / AWS UNCONFIGURED / AWS CONFIGURED; unavailable metrics show "Unavailable".

## Integration status in this build
| Integration | State |
|---|---|
| Local store, queue, notification sink | LOCAL (works) |
| Notification simulator (email/SMS/WhatsApp) | SIMULATED |
| Governance: local dev provider | SIMULATED (test-only decisions) |
| UNWIND adapter | UNCONFIGURED until env set; contract untested against a live UNWIND |
| AWS Step Functions / SQS / SNS / CloudWatch adapters | UNCONFIGURED; unit-tested with fakes only |
| WhatsApp Cloud API adapter | UNCONFIGURED; implemented per public contract, never run against the live API |

## Honest status / known limitations
- Engine runs on the local SQLite store/queue; AWS adapters are not wired as system of record.
- No live test of AWS, WhatsApp or UNWIND. SNS delivery receipts and SMS delivery status are not consumed (stay `ACCEPTED`).
- Dev auth only (static tokens); production auth provider is an interface, not an implementation. Dev server is single-process, loopback-bound.
- SQLite is not encrypted; retention scrub exists (`purge_expired`, run every ~10 min by the dev server loop).
- Notification workflow completion does not wait for delivery.
- The UI's "Real send" uses browser `prompt()` for inputs, then a confirmation dialog; it is functional, not polished.
- No screenshots are included (none were generated).

Docs index: `docs/ARCHITECTURE.md`, `WORKFLOW_STATE_MACHINE.md`, `GOVERNANCE_AND_APPROVALS.md`, `NOTIFICATION_POLICY.md`, `AWS_DEPLOYMENT_GUIDE.md`, `AWS_SECURITY_AND_IAM.md`, `OBSERVABILITY_AND_RUNBOOKS.md`, `API_AND_SCHEMAS.md`, `INTEGRATION_CONTRACT.md`, `THREAT_MODEL.md`, `AUDIT_AND_PLAN.md`, `TEST_REPORT.md`.
