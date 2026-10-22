# AEGISNOVA Reuse Decisions & Architectural Ledger
**Generated:** October 20, 2026  
**Status:** Approved for Implementation (Phase 1)

---

## 1. Evidence-Based Reuse Decision Matrix

| Capability | Source Repository | Evidence Inspected | Decision | Required Changes | Confidence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Command Center Layout & Design System** | DevGuard Enterprise | `frontend/app/command/page.tsx`, `components/command/*`, Tailwind config | **ADAPT** | Rethemed to AEGISNOVA palette (dark graphite, cyan/sky blue); extracted into unified 10-screen shell. | High |
| **Scanner Engine (Static / Rule-Based)** | DevGuard AI | `backend/core/ai_agent.py`, `backend/core/schemas.py`, `/scan` endpoint | **WRAP** | Expose behind versioned contract `ScanJob` & `Finding`. Add client adapter with safe mock fallback. | High |
| **Fixer / Remediation Generator** | DevGuard AI | `backend/core/ai_agent.py` patch synthesis logic | **WRAP** | Decouple from auto-application. Wrap behind UNWIND human approval gate for all high-risk writes. | High |
| **Validator Gate** | DevGuard AI | AST validation and test execution harness in `backend/core/` | **ADAPT** | Adapt to enforce deterministic proof before patch proposal is promoted to ready state. | High |
| **Governance Core & Approvals** | UNWIND | `warrant/ledger.py`, `court/protocol.py`, `warrant/DESIGN.md` | **REUSE** | Adopt UNWIND as the single platform governance authority. Pure integer warrant fold and capability scopes. | High |
| **Decision Lineage & Audit Trail** | UNWIND & DevGuard Enterprise | `tests/test_audit_chain.py` (Enterprise) and UNWIND append-only ledger | **REUSE** | Standardize on SHA-256 hash-linked lineage for all human approvals and warrant debits. | High |
| **Downstream Blast Radius Traversal** | DevGuard Enterprise & UNWIND | `backend/v2/ml_impact.py` (Enterprise) and T0 graph traversal (`unwind`) | **ADAPT** | Combine Enterprise impact UI with UNWIND zero-model arithmetic filtering (`shock > slack`). | High |
| **Telemetry & Observability** | DevGuard AI | OpenTelemetry FastAPI instrumentation, SigNoz collector setup | **WRAP** | Wrap behind standard OpenTelemetry collector endpoint with correlation ID propagation. | High |
| **Replay Manifest & Static Proofs** | DevGuard Enterprise | `public/replay/manifest.json`, `backend/v2/replay.py` | **ADAPT** | Adapt replay bundle format into AEGISNOVA demo and offline demonstration mode. | High |
| **Feature 01: NightShift SDE** | Future ZIP 01 | Architecture requirements only (ZIP not provided) | **DEFER** | Reserved UI slot and `WorkflowRun` contract. Keep status in `PLANNED` until ZIP intake. | High |
| **Feature 02: Evidence Intelligence** | Future ZIP 02 | Architecture requirements only (ZIP not provided) | **DEFER** | Reserved UI slot and `EvidenceReference` contract. Keep status in `PLANNED` until ZIP intake. | High |
| **Feature 03: Causal Impact Intelligence** | Future ZIP 03 | Architecture requirements only (ZIP not provided) | **DEFER** | Reserved UI slot and `ImpactAnalysis` contract. Keep status in `PLANNED` until ZIP intake. | High |
| **Feature 04: Independent Repair Assurance**| Future ZIP 04 | Architecture requirements only (ZIP not provided) | **DEFER** | Reserved UI slot and `RepairProof` contract. Keep status in `PLANNED` until ZIP intake. | High |
| **Feature 05: Autonomous Ops & Notifications** | Future ZIP 05 | Architecture requirements only (ZIP not provided) | **DEFER** | Reserved UI slot and `NotificationStatus` contract. Keep status in `PLANNED` until ZIP intake. | High |

---

## 2. Decision Justifications & Safety Boundaries

### 2.1 ADAPT: Command Center Layout & Design
- **Why Not Copy Wholesale?** Copying DevGuard Enterprise wholesale would bring along legacy branding, outdated routes (`/nexus`, `/command`), and hardcoded replay paths.
- **AEGISNOVA Strategy:** Built an original, clean Next.js 14 App Router shell featuring AEGISNOVA branding, unified top bar, responsive sidebar navigation, and reusable design components (`Card`, `Badge`, `MetricCard`, `Modal`).

### 2.2 WRAP: DevGuard AI Scanner & Fixer Engine
- **Why Wrap Behind Adapters?** Running untrusted code scanning or raw LLM completions directly from the UI creates security and stability risks.
- **AEGISNOVA Strategy:** Wrapped the scanner and fixer behind typed schemas (`ScanJob`, `Finding`, `PatchProposal`). High-risk file mutations are blocked from auto-execution and routed directly to the UNWIND approval inbox.

### 2.3 REUSE: UNWIND as the Single Governance Core
- **Why UNWIND?** UNWIND provides a deterministic, zero-model authority model (`warrant/ledger.py`) where authority cannot be minted by an agent or LLM. It decays over time, is scoped to capabilities, and requires human countersignatures for consequential actions.
- **AEGISNOVA Strategy:** UNWIND is documented and integrated as the sole Governance Core. No duplicate or competing approval engines exist.

### 2.4 DEFER: Five Future Feature Modules
- **Rule:** As mandated by the canonical product vision, the five feature ZIPs have not been supplied in this phase.
- **AEGISNOVA Strategy:** Rather than fabricating hypothetical code, we established versioned TypeScript contracts and dedicated integration slots, keeping their health status honestly labelled as `PLANNED`.
