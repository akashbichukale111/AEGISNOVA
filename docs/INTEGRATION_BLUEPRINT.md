# AEGISNOVA Integration Blueprint
**Product:** AEGISNOVA  
**Tagline:** A New Standard for Safe AI  
**Version:** 1.1.0 (Phase 2 - Workstream 05 Integrated)

---

## 1. Architectural Architecture Overview

AEGISNOVA unifies foundational capabilities into a singular enterprise platform:
1. **Command Surface & Observability (DevGuard Enterprise):** Enterprise command-center UX, real-time telemetry, blast radius inspection, and incident coordination.
2. **Security & Remediation Core (DevGuard AI):** Resilient static/AST vulnerability scanner, automated patch synthesizer (Fixer), and deterministic syntax/test validator.
3. **Universal Governance Core (UNWIND):** Zero-model deterministic warrant ledger, capability-scoped authority leasing, approval timeout/revocation, and immutable decision lineage.
4. **Autonomous Operations & Notifications (Workstream 05 - CONNECTED):** Resilient Python-based state machine, idempotency ledger, multi-channel notification outbox, dead-letter quarantine (DLQ), and operational reliability telemetry.

```
+-----------------------------------------------------------------------------------+
|                            AEGISNOVA MAIN PRODUCT SHELL                           |
|       (Next.js 14 App Router, Dark Command Center Design System, TypeScript)      |
+-----------------------------------------------------------------------------------+
  |               |                |                     |                 |
  v               v                v                     v                 v
Overview     Security Center   Governance       Repository & Impact   Operations Center
  |               |                |                     |                 |
  |               v                v                     |                 v
  |        [DevGuard AI]     [UNWIND Core]               |        [Next.js API Proxy]
  |       Scanner / Fixer    Warrant Ledger              |        /api/operations/*
  |          Validator      Human Approvals              |                 |
  |               |                |                     |                 v
  |               |                |                     |        [Python Engine]
  |               |                |                     |        127.0.0.1:8080
  |               |                |                     |        (Local SQLite/DLQ)
  +---------------+----------------+---------------------+-----------------+
                                   |
                  +---------------------------------+
                  |   FUTURE FEATURE MODULE SLOTS   |
                  |  01: NightShift SDE (PLANNED)   |
                  |  02: Evidence Intel (PLANNED)   |
                  |  03: Causal Impact (PLANNED)    |
                  |  04: Repair Assur. (PLANNED)    |
                  +---------------------------------+
```

---

## 2. UNWIND Governance Core Role & Adapter Contract

UNWIND operates as the **single source of authority** within AEGISNOVA. No agent, background worker, or autonomous pipeline can authorize high-risk actions (such as mutating repository code, rotating credentials, or altering production infrastructure) without an active capability lease or human countersignature.

### 2.1 The Warrant Ledger
- **Pure Integer Arithmetic:** The warrant balance is an integer count of basis points (e.g. `1,450 bp`). It utilizes no floating point arithmetic, eliminating non-deterministic rounding errors.
- **Zero-Model Guarantee:** Authority is evaluated deterministically without relying on LLM inference. An outage of Vertex AI or external inference engines cannot impair governance decisions.
- **Decaying Authority:** Authority leases decay automatically during idle periods, preventing stale or forgotten permissions from being exploited.

### 2.2 Governance Adapter Interface
```typescript
export interface ApprovalRequest {
  schemaVersion: "1.0.0";
  id: string; // e.g. "APPR-SEC-081"
  actionType: "APPLY_SECURITY_PATCH" | "RETRY_JOB" | "INFRA_MUTATION" | "SECRET_ROTATION";
  actionPayload: Record<string, unknown>;
  severity: SeverityLevel;
  requiredScope: string; // e.g. "scope:repo:write"
  warrantDebitBp: number;
  expiresAt: string;
  createdAt: string;
  state: "PENDING" | "APPROVED" | "REJECTED" | "REVOKED" | "EXPIRED";
  requestedBy: string;
}

export interface ApprovalDecision {
  schemaVersion: "1.0.0";
  approvalRequestId: string;
  decision: "APPROVED" | "REJECTED" | "REVOKED";
  decidedBy: string;
  decidedAt: string;
  decisionReason: string;
  decisionLineageHash: string;
  warrantBalanceRemainingBp: number;
}
```

---

## 3. DevGuard AI Security Core Integration Boundary

The Scanner, Fixer, and Validator pipeline from DevGuard AI is integrated via clean API contracts:

1. **Scanner Request:** Transmits repository identifier, target commit hash, and rule profile. Trace continuation headers (`traceparent`) ensure telemetry spans are correlated from the frontend down to AST parsing.
2. **Fixer Synthesis:** When a vulnerability is triaged, the Fixer proposes a minimal unified diff and explanation. Crucially, **the Fixer is prohibited from applying changes directly to disk**.
3. **Governance Pause Gate:** If a patch proposal carries `HIGH` or `CRITICAL` severity, the workflow automatically transitions to `PAUSED_APPROVAL` and emits an `ApprovalRequest` to UNWIND.
4. **Validator Execution:** Upon receiving human authorization, the patch is tested against an isolated syntax and unit test runner.

---

## 4. Shared Versioned Data Contracts (v1.0.0)

All platform components exchange data using the canonical contracts defined in `src/contracts/index.ts`:

1. `Repository`: Workspace configuration, branch references, and monitoring status.
2. `ScanJob`: Asynchronous vulnerability scan execution and status.
3. `Finding`: Individual vulnerability or security violation (CWE, secret leak, prompt injection).
4. `PatchProposal`: Remediation diff, confidence metric, and governance requirements.
5. `ValidationResult`: Deterministic syntax and test execution proofs.
6. `WorkflowRun`: Checkpoint-tracked autonomous execution states.
7. `ApprovalRequest`: UNWIND gate request for consequential action delegation.
8. `ApprovalDecision`: Human countersignature, revocation reason, and lineage hash.
9. `EvidenceReference`: External vulnerability intelligence citations.
10. `ImpactAnalysis`: Downstream dependency blast radius and causal rankings.
11. `RepairProof`: Adversarial patch breaker verification and warranty certificates.
12. `NotificationStatus`: Multi-channel alert delivery metrics (SNS, WhatsApp, Slack).
13. `AuditEvent`: Append-only security and operational telemetry records.
14. `IntegrationHealth`: Module status (CONNECTED, PLANNED, NOT CONNECTED).

---

## 5. Correlation & Traceability Model

Every operation across the platform carries a stable `correlationId` (e.g., `corr-77a8-99b2`).
- The `correlationId` connects the initial `ScanJob` to the identified `Finding`, the proposed `PatchProposal`, the corresponding UNWIND `ApprovalRequest`, the final `ValidationResult`, and the resulting `AuditEvent`.
- Any operator or auditor can trace the complete provenance of a code mutation from initial discovery to human approval and deployment in a single query.
