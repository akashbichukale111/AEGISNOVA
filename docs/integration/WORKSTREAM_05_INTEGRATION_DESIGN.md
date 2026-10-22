# Workstream 05 Integration Design & Architecture
**Product:** AEGISNOVA  
**Subsystem:** Autonomous Operations & Notifications (Workstream 05)  
**Date:** October 21, 2026

---

## 1. Chosen Service Boundary

The standalone engine is written in standard-library Python (>=3.10), whereas the AEGISNOVA main product is built on Next.js 14 and TypeScript. Rather than forcing incompatible runtimes into a single process, the architecture establishes a clean, decoupled boundary:

```
[ Browser (AEGISNOVA UI) ]
            |
            | HTTPS / JSON (Session Cookies / Same-Origin)
            v
[ Next.js Server Adapter: /api/operations/* ]
            |
            | Loopback HTTP (127.0.0.1:8080) + Server-Side Bearer Token
            v
[ Autonomous Operations Engine (services/autonomous-operations) ]
            |
            +---> SQLite Store (.data/aegisnova_ops.db)
            +---> Local Queue / DLQ Scheduler
            +---> Local Notification Sink
            +---> UNWIND Governance Bridge (Adapter)
```

### 1.1 Why This Boundary?
1. **Security Isolation:** Internal authorization tokens (`tok-admin`, `tok-operator`) remain server-side within the Next.js API layer. The browser client receives only sanitized data with PII/destinations masked.
2. **Reliability & Resilience:** If the Python background service is stopped, restarting, or upgrading, the Next.js shell remains fully operational, displaying a truthful `SERVICE_OFFLINE` indicator with manual retry options.
3. **No Docker / Cloud Requirement:** Both processes run natively on Windows/Linux with zero external cloud dependencies.

---

## 2. Request & Response Flow

1. **User Action:** Operator navigates to `/operations` or triggers an action (e.g., start sample workflow, retry DLQ item, approve local test request).
2. **Next.js Client:** Dispatches standard fetch to `/api/operations/workflows`, `/api/operations/approvals`, etc.
3. **Next.js Route Handler (`src/app/api/operations/[...slug]/route.ts`):**
   - Validates user session and permissions.
   - Forwards HTTP method, query parameters, and JSON body to `http://127.0.0.1:8080/{path}`.
   - Injects the configured internal `OPERATIONS_INTERNAL_TOKEN`.
   - Handles timeout and connection errors, returning structured `{ error: "OPERATIONS_SERVICE_UNAVAILABLE", ... }` on failure.
4. **Operations Engine (`aegisnova_ops`):**
   - Validates input contracts (`contracts.py`).
   - Appends events to SQLite `events` table (append-only trigger enforced).
   - Returns sanitized payload.

---

## 3. Governance Integration Architecture

The standalone service comes with a local HMAC-SHA256 governance envelope (`governance.py`). However, AEGISNOVA mandates **UNWIND as the single platform authority**:
- Operations approval requests are mirrored to AEGISNOVA's UNWIND Governance Core.
- The approval gate blocks any consequential or high-risk write until authorized.
- In local development mode, local approvals are clearly flagged as `DEVELOPMENT / TEST ONLY`. Production credentials cannot be verified until live UNWIND wire contracts are established.

---

## 4. Persistence & File Structure

```
d:\AEGISNOVA\
├── services\
│   └── autonomous-operations\       # Self-contained Python service
│       ├── aegisnova_ops\           # Engine modules
│       ├── tests\                   # Python unit tests
│       ├── .data\                   # SQLite DB (ignored by git)
│       └── README.md                # Service-specific documentation
├── src\
│   ├── app\
│   │   ├── api\operations\          # Next.js API Proxy routes
│   │   └── operations\page.tsx      # Upgraded Operations Center UI
│   └── contracts\index.ts           # Extended TypeScript contracts
```
