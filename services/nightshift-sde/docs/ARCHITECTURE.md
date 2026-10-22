# NightShift SDE — architecture (standalone build)

A **modular monolith**, Python standard library only, SQLite (WAL) as the single durable source of truth. No in-memory queue or variable is ever the sole record of a job.

```
Repository registry ─┐
Schedules (tick) ────┼─► trigger validation + idempotency ─► durable job row (QUEUED)
Webhook (HMAC) ──────┤                                            │ claim (lease + fence token)
Manual / UI / API ───┘                                            ▼
        VALIDATING → SNAPSHOTTING → INSPECTING → RESEARCHING → EVIDENCE_REVIEW → RISK_ASSESSMENT
              ▲  (each stage persists a checksummed checkpoint)          │ deterministic policy gate
              │                                  read-only ─► COMPLETED_WITH_WARNINGS / COMPLETED (investigation)
   resume from last VALID checkpoint                         │ repair-eligible + allow_repair
              │                                              ▼
              └──────────────  WAITING_FOR_APPROVAL (scoped grant, expiry, revocation, separation of duties)
                                                             ▼
                                   READY_TO_EXECUTE (re-validates base commit / policy / evidence / approval)
                                                             ▼
                          EXECUTING → TESTING (sandbox) → INDEPENDENT_VERIFICATION → Repair Proof artifact
Watchdog (tick): expired leases, stalled jobs, missed schedules, queue age/depth, DLQ growth, provider failures,
                 stale checkpoints, orphaned workspaces, silent workers, crash loops  → alerts + guarded recovery
```

| Module | Responsibility |
|---|---|
| `statemachine.py` | 22 states, explicit transition table, terminal invariants, resume map |
| `store.py`, `db.py`, `migrations/` | transactional persistence, leases + fencing, checkpoints, hash-chained audit events, outbox-style notifications, reversible migration |
| `schedule.py` | recurrence maths (DST-aware), schedule CRUD, restart-safe tick (3 duplicate-firing guards), missed-run policy |
| `worker.py`, `runtime.py` | stage pipeline, lease heartbeat, cancellation points, in-process threads (local mode) |
| `retry.py`, `errors.py` | transient/permanent classification, exponential backoff + jitter, budgets, recovery hints |
| `manifests.py`, `versions.py`, `evidence.py`, `providers.py` | requirements.txt / package.json(+lock) parsing, version ranges, evidence reconciliation (conflict/stale), advisory providers (local files; OSV optional) |
| `risk.py` | deterministic risk score, reason codes, repair eligibility |
| `governance.py` | **adapter interface + labelled dev stub** for UNWIND approvals (scope hash, expiry, revoke, SoD) |
| `repair.py`, `sandbox.py`, `verifier.py` | minimal-version patch in a temp workspace, allowlisted commands in a network-isolated, rlimited sandbox, independent re-verification, Repair Proof |
| `watchdog.py` | detections and guarded auto-recovery |
| `redact.py`, `untrusted.py` | secret redaction in logs/API; untrusted-content handling (repository text is data, never instructions) |
| `server.py`, `service.py` | HTTP API + static console; every entry point goes through `App` for authz/idempotency/audit |
| `ui/` | ES-module console (no build step, strict CSP, no `innerHTML`) |

## Truthfulness rules encoded in the data model
* `COMPLETED*` never implies a repair: `jobs.outcome` distinguishes `investigation_only`, `no_findings`, `repair_verified`, `repair_blocked`, …
* A patch artifact exists only after tests pass; `repair_verified` requires the verifier to agree.
* Approvals are scoped to repository, base commit/tree, paths, diff hash, policy and expiry; any change invalidates them.
* No fabricated history: `seed-demo` registers synthetic repos only; every job, finding and metric comes from real execution.

## Integration points for the later AEGISNOVA merge (NOT connected today)
`governance.py` (UNWIND), `verifier.py` (Independent Repair Assurance), `providers.py` (advisory/Evidence Intelligence), `service.App.handle_webhook` (GitHub). AWS (EventBridge Scheduler, Step Functions, SQS+DLQ, SNS, S3, Secrets Manager, CloudWatch) is **design-only**: see `docs/AWS.md`.
