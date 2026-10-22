# AEGISNOVA Known Limitations & Operational Boundaries
**Product:** AEGISNOVA  
**Version:** 1.1.0 (Phase 2 Deliverable)

---

## 1. Operational State Classification

To maintain documentation and operational integrity, all platform capabilities are explicitly categorized into distinct operational states:

| Category | Definition | Capabilities Currently in this Category |
| :--- | :--- | :--- |
| **LIVE / VERIFIED** | Connected to runnable local code and verified by automated tests. | Product Shell & Routing, Command Launcher (Ctrl+K), Responsive Design System, 14 Shared Schema Contracts (`src/contracts/index.ts`), Automated Smoke Test Suite (`npm test`), Build Bundler (`next build`), **Autonomous Operations & Notifications Backend (`services/autonomous-operations` on `127.0.0.1:8080`)**, Next.js Server API Proxy (`/api/operations/*`), Live End-to-End Operational Pipeline. |
| **DEMO / RESILIENT ADAPTER** | Fully interactive UI wired to deterministic local demo state and resilient mock adapters. No external network or cloud required. | DevGuard AI AST Scanner simulation, Fixer patch proposal & unified diff viewer, Validator gate preview, UNWIND Warrant Ledger basis-point fold (`1,450 bp`), Human Approval countersignature dialog, Correlated audit event timeline. |
| **UNCONFIGURED (FAIL-CLOSED)** | Wire adapters or cloud connectors implemented in code but intentionally unconfigured without live credentials. | AWS SNS/Step Functions adapters, WhatsApp Cloud API adapter, Live external UNWIND HTTP wire adapter. |
| **PLANNED (SLOT)** | Fully specified contract and reserved UI integration slot. Code implementation intentionally deferred until ZIP archive intake. | 01: NightShift SDE, 02: Evidence Intelligence, 03: Causal Impact Intelligence, 04: Independent Repair Assurance. |

---

## 2. Specific Technical Limitations & Operational Boundaries

### 2.1 Autonomous Operations & Notifications (Workstream 05)
- **Local Loopback Microservice:** The operations engine runs locally via Python 3 on `http://127.0.0.1:8080` backed by SQLite. Workflows are processed asynchronously via an in-memory queue and SQLite state machine.
- **Accepted ≠ Delivered:** Notification requests to local sinks or SNS are recorded as `ACCEPTED`. They are only transitioned to `DELIVERED` if cryptographic delivery receipts are received and validated. In local development mode, notifications remain in `ACCEPTED` or `LOCAL_RECORDED` states.
- **UNWIND Authority Boundary:** Local operations approval endpoints are strictly designated as `[DEVELOPMENT / TEST ONLY]` to prevent circumventing the authoritative UNWIND Governance Core.
- **No Cloud Resources Provisioned:** AWS SNS, Step Functions, SQS, and Meta WhatsApp Cloud APIs remain completely unconfigured. Zero cloud resources have been provisioned, and no external network calls are made.

### 2.2 External Cloud & Model Providers
- **No Production Cloud Resources Provisioned:** Neither AWS SNS/SQS, GCP Firestore, nor Cloud Run resources have been provisioned in this phase.
- **Inference Client Isolation:** Vertex AI and Groq inference calls default to deterministic mock responses (`UNWIND_VERTEX_DISABLED=1`). This guarantees that external provider rate limits, network failures, or API deprecations cannot block the AEGISNOVA main UI or test suite.

### 2.2 Patch Application Safety Boundary
- While the Security Center allows the operator to preview, review, and countersign patches (e.g. `FIND-SEC-101`), the UI strictly requires human confirmation before updating the in-memory state. Direct writes to disk are governed by UNWIND capability scope leases.

### 2.3 Unverified Areas
- **Transitive Package Compatibility with Node 24:** While Next.js 14.2.35 builds cleanly with Node 24.18.0, certain native build addons in the legacy repositories (such as `monaco-editor` native bindings) require standard Node 20 LTS for long-term production container deployment.
- **Upcoming Feature ZIP Contents:** The internal architectures and dependencies of the five future ZIPs remain uninspected until supplied by the user.

---

## 3. Safe Remediation Guidance

- **Environment Configuration:** Copy `.env.example` to `.env.local` to override default adapter URLs.
- **Node Environment:** Prepend `C:\Users\hp\Desktop\nvm\v24.18.0` to your path when running build or dev commands if not globally present in the current terminal session.
