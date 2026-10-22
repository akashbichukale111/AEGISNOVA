# AEGISNOVA Workstream 05: Integration Ledger

**Last Updated:** 2026-10-21  
**Status:** Integrated & Verified  
**Scope:** Workstream 05 (Autonomous Operations & Notifications) into AEGISNOVA Main Product Shell  

---

## 1. System Components & Connectivity Ledger

| Component / Subsystem | Integration State | Operational Mode | Authority / Provider | Notes |
|---|---|---|---|---|
| **AEGISNOVA Main Shell** | `LIVE` | Next.js 14 App Router | Unified Nav & Layout | Runs on `http://localhost:3000` |
| **Operations Center (`/operations`)** | `CONNECTED` | Integrated React / Tailwind | Python Operations Service | Full 8-tab operations dashboard |
| **Operations Server API Proxy** | `CONNECTED` | Next.js Route Handler | Internal Loopback Proxy | Proxies `/api/operations/*` -> `127.0.0.1:8080` with dynamic token resolution |
| **Python Operations Service** | `CONNECTED` | Standard Library Python | Local Engine (`sqlite3`) | Runs on `http://127.0.0.1:8080` under `services/autonomous-operations` |
| **UNWIND Governance Core** | `AUTHORITATIVE_MAPPED` | Local Architecture / Concept | Single Authority | Real approvals gated via UNWIND concepts. Ops test actions explicitly badged as `[DEVELOPMENT / TEST ONLY]` |
| **Local SQLite Outbox & Store** | `LIVE_LOCAL` | File/Memory SQLite | Local-first Engine | Auto-migrated schema, atomic transitions |
| **Notification Outbox** | `LIVE_LOCAL` | In-process Outbox Sink | Local Sink (`local_sink`) | Masks destinations, records delivery attempts |
| **AWS SNS / Step Functions** | `UNCONFIGURED` | Stub / Adapter Only | Cloud Provider | Unconfigured by design. No credentials loaded, no network calls |
| **WhatsApp Cloud API** | `UNCONFIGURED` | Stub / Adapter Only | Meta Graph API | Unconfigured by design. Requires live access token & webhook secret |
| **Live UNWIND Wire Adapter** | `UNCONFIGURED` | Wire Adapter Ready | UNWIND HTTP Endpoint | Defaults to fail-closed waiting state if URL is unset |

---

## 2. Operations Center (`/operations`) Sub-Tabs Ledger

| Sub-Tab | Purpose | Real Data Source | User Actions | State Badges |
|---|---|---|---|---|
| **1. Overview** | High-level metrics, active runs, engine status | `/api/operations/overview` | Quick filters, refresh | `CONNECTED` / `OFFLINE` badge |
| **2. Workflow Runs** | Workflow execution history & live progress | `/api/operations/runs` | Start Workflow modal, inspect timeline, cancel run | `QUEUED`, `RUNNING`, `WAITING_FOR_APPROVAL`, `SUCCEEDED`, `FAILED` |
| **3. Approval Inbox** | Human-in-the-loop governance requests | `/api/operations/approvals` | Inspect approval details, Grant/Reject test decision | Clear `[DEVELOPMENT / TEST ONLY]` badge on all local actions |
| **4. Notifications** | Notification audit log & delivery states | `/api/operations/notifications` | View payload, replay dead notifications | `ACCEPTED` (not delivered), `DELIVERED`, `DEAD_LETTERED` |
| **5. Queues & DLQ** | Queue inspection, error quarantine & redrive | `/api/operations/dlq` | Inspect error class, redrive item with confirmation | `VISIBLE`, `IN_FLIGHT`, `DEAD_LETTER` |
| **6. Reliability & Alerts** | Operational alarms & SLO tracking | `/api/operations/reliability` | Inspect alarm state & threshold conditions | `OK`, `ALARM`, `UNAVAILABLE` |
| **7. Event Log** | Append-only audit trail with correlation IDs | `/api/operations/events` | Filter by correlation ID or run ID | Immutable event records |
| **8. Integrations** | Status of external connectors & providers | `/api/operations/integrations` | View connector states and required config | `LOCAL`, `UNCONFIGURED`, `CONFIGURED` |

---

## 3. Route & Contract Ledger

### Application Routes
- `/` — Main Executive Dashboard (`READY`)
- `/security` — Security Center (`READY`)
- `/operations` — Autonomous Operations & Notifications (`CONNECTED - WS05`)
- `/governance` — UNWIND Governance Core (`READY`)
- `/evidence` — Evidence Intelligence (`PLANNED - WS02`)
- `/causal-impact` — Causal Impact Intelligence (`PLANNED - WS03`)
- `/repair-assurance` — Independent Repair Assurance (`PLANNED - WS04`)
- `/impact` — Impact Analysis Center (`READY`)
- `/audit` — Audit & Observability Center (`READY`)
- `/settings` — Integration Registry & Settings (`READY`)

### Contract Extensions in `src/contracts/index.ts`
- `WorkflowRun`: Extended with `requires_approval`, `attempts`, `payload_hash`, `tenant`, and `timeline`.
- `WorkflowTimelineEvent`: Added to model append-only run state transitions.
- `NotificationStatus`: Extended with `mode`, `channel`, `destination_masked`, `attempts`, and `receipt_verified`.
- `DeadLetterItem`: Added to model DLQ items, error classes, and redrive history.
- `OperationalAlarm`: Added to model reliability metrics and alarm conditions.
