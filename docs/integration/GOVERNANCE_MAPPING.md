# AEGISNOVA Governance Mapping: Operations & UNWIND Core
**Subsystem:** Governance Integration  
**Authority:** UNWIND Governance Core  
**Date:** October 21, 2026

---

## 1. Single Authority Policy

Under AEGISNOVA architecture, **UNWIND is the sole Governance Core**. No satellite service (including the autonomous operations engine) is permitted to instantiate a competing or secondary production approval authority.

```
                      +-----------------------------+
                      |   UNWIND GOVERNANCE CORE    |
                      |  (Single Platform Authority)|
                      +-----------------------------+
                                     ^
                                     | Scoped Countersignature
                                     | & Warrant Debit Fold
                      +--------------+--------------+
                      |                             |
             [ DevGuard AI Gating ]      [ Autonomous Ops Adapter ]
              (Scanner/Fixer Writes)      (Workflow Consequential Acts)
```

---

## 2. Protocol & Schema Mapping

The standalone operations service defines an approval request structure in `aegisnova_ops/store.py` and a signed HMAC envelope in `aegisnova_ops/governance.py`. These map into AEGISNOVA's canonical `ApprovalRequest` and `ApprovalDecision` types:

| Workstream 05 Field | AEGISNOVA Contract Field | Semantics & Transformation |
| :--- | :--- | :--- |
| `id` | `id` | Stable identifier (`APPR-OPS-xxx`). |
| `run_id` | `actionPayload.workflowRunId` | Binds decision to specific workflow execution. |
| `action` | `actionType` | Mapped to capability action (`APPLY_SECURITY_PATCH`, `INFRA_MUTATION`, `RETRY_JOB`). |
| `scope` | `requiredScope` | Scoped authority string (`scope:repo:write`, `scope:ops:execute`). |
| `risk_level` | `severity` | Risk classification (`CRITICAL`, `HIGH`, `MEDIUM`). |
| `action_hash` | `actionPayload.actionHash` | Cryptographic SHA-256 fingerprint of the proposed mutation. |
| `expires_at` | `expiresAt` | ISO 8601 timestamp. Past timestamps trigger `EXPIRED` status immediately. |
| `decision_ref` | `decisionLineageHash` | Immutable lineage hash appended to audit chain. |
| `status` | `state` | `PENDING` -> `APPROVED` | `REJECTED` | `REVOKED` | `EXPIRED`. |

---

## 3. Strict Security Rules Enforced

1. **Fail-Closed Gate:** If a workflow requires approval, execution halts at state `PAUSED_APPROVAL`. If UNWIND is unreachable or unconfigured, the workflow remains paused indefinitely until an authorized decision is submitted. It **never** auto-completes.
2. **Local Test Approvals Are Non-Production:** Any decision issued via the local development key (`LocalDevGovernance`) is visually and semantically tagged as:
   `[DEVELOPMENT / TEST ONLY — NOT PRODUCTION AUTHORIZATION]`.
3. **Tamper & Replay Protection:** Decision events include a nonce and action hash. Replayed, expired, or hash-mismatched decisions are rejected by the engine with HTTP 409/422.
4. **Warrant Accounting:** In the live UNWIND model, each approved action debits basis points from the tenant's warrant balance (`1,450 bp`).
5. **No Production Key in Source:** The default local HMAC secret key from the standalone ZIP is restricted strictly to local test mode. Production environments require external key rotation via KMS.

---

## 4. Current Status & Limitations

- **Local Governance Bridge:** Functional in local mode via server-side proxy.
- **Live UNWIND Wire Adapter:** **UNCONFIGURED**. Wire contracts between the Cloud Run UNWIND service and this engine have not been exercised live; consequential operations remain safely gated.
