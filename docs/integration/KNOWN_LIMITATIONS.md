# Workstream 05 Integration: Known Limitations & Boundaries

**Product:** AEGISNOVA  
**Integration Phase:** Phase 2 (Workstream 05: Autonomous Operations & Notifications)  
**Last Updated:** 2026-10-21  

---

## 1. Executive Summary of Operational States

AEGISNOVA adheres to a strict principle of truth in advertising. No mock is presented as live, and no external provider is reported as connected unless actual runtime verification and authorization exist.

| Capability | Current State | Verification Basis | Boundary / Limitation |
|---|---|---|---|
| **Operations Engine Core** | `LIVE LOCAL` | Python 3.13 + SQLite on `127.0.0.1:8080` | Local loopback service; processes real workflows in local SQLite database. |
| **Next.js UI & API Proxy** | `LIVE LOCAL` | Next.js 14 App Router on `localhost:3000` | Securely proxies requests to loopback with session/token authentication. |
| **Local Notification Outbox** | `LIVE LOCAL` | In-process Outbox Sink | Stores outgoing notifications locally; records delivery attempts. |
| **Development Approvals** | `LOCAL / TEST ONLY` | Local State Machine Transition | Not authoritative for production; clearly badged `[DEVELOPMENT / TEST ONLY]` to prevent confusion with UNWIND Governance Core. |
| **UNWIND Live Wire Adapter** | `UNCONFIGURED` | Network Stub | Wire contract defined; fails closed (`WAITING_FOR_APPROVAL`) if live UNWIND HTTP service is unreachable or unconfigured. |
| **AWS Cloud (SNS / Step Functions)** | `UNCONFIGURED` | Unit Test Fakes Only | Zero AWS resources deployed. No credentials loaded into environment. |
| **WhatsApp Cloud API** | `UNCONFIGURED` | Unit Test Fakes Only | Zero Meta Graph API calls made. No live WhatsApp token or webhook configured. |

---

## 2. Notification Delivery Semantics

1. **Accepted ≠ Delivered:**
   - When a notification is published via SNS or recorded in local outbox, its status is marked `ACCEPTED`.
   - The status is ONLY upgraded to `DELIVERED` if an authenticated, cryptographic delivery receipt is processed.
   - For local mode, notifications remain in `ACCEPTED` or `LOCAL_RECORDED` states to avoid false claims of real-world delivery.
2. **PII Masking by Default:**
   - All email addresses and phone numbers in outbox logs, UI tables, and API responses are masked at the service boundary (e.g., `o***@aegisnova.local`).
3. **Storm Suppression & Rate Limits:**
   - The notification dispatcher applies per-recipient suppression and circuit breakers to prevent alert fatigue.

---

## 3. UNWIND Governance Single-Authority Boundary

1. **Why Local Approvals are Segregated:**
   - AEGISNOVA's core architectural principle dictates that **UNWIND is the sole authoritative Governance Core**.
   - The Python operations service includes local approval decision endpoints for standalone unit testing and local development.
   - In the integrated AEGISNOVA UI, these buttons are explicitly labeled with `[DEVELOPMENT / TEST ONLY]` warning banners.
2. **Production Evolution:**
   - In production, approvals are issued exclusively through UNWIND's signed token exchange mechanism.
   - The operations service validates UNWIND Ed25519 or HMAC signatures before advancing workflows out of `WAITING_FOR_APPROVAL`.

---

## 4. Credential & Security Posture

1. **Zero Exposed Live Secrets:**
   - No live API keys, AWS credentials, WhatsApp bearer tokens, or production JWT signing secrets are stored in this workspace or committed to source control.
   - All test secrets in test files are intentionally synthetic test fixtures (e.g., `test-secret-value`).
2. **Internal Proxy Security:**
   - The Python backend requires Bearer token authentication on all administrative and operational endpoints.
   - During local startup, an internal authentication token is dynamically generated in `.local/dev-tokens.json` or supplied via `AEGIS_INTERNAL_TOKEN`.
   - The Next.js API route handler reads this internal token securely on the server side; no tokens are exposed to the browser client.

---

## 5. Unsupplied Future Modules

The remaining four feature modules have not been provided or integrated in this phase:
- Workstream 01: NightShift SDE
- Workstream 02: Evidence Intelligence
- Workstream 03: Causal Impact Intelligence
- Workstream 04: Independent Repair Assurance

Their routes (`/evidence`, `/causal-impact`, `/repair-assurance`) remain in their clean, documented Phase 1 placeholder states with clear integration contracts defined in `src/contracts/index.ts`.
