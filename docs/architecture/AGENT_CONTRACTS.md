# AEGISNOVA — Agent Contracts & Data Models

**Architecture Specification:** Phase 3 — Autonomous Engineering with Verifiable Trust  
**Signature Feature:** Proof-Carrying Pull Requests (PCPR)  
**Schema Standard:** `src/contracts/index.ts`  

---

## 1. Multi-Agent Role & Responsibility Matrix

| Agent Role | Responsibility | Input Contract | Output Contract | Verification Boundary |
|---|---|---|---|---|
| **A. Repository Intelligence** | Scans repo manifests, AST entry points, test commands | `RepositoryTarget` | Grounded Architecture Map | Real manifest files parsed on disk |
| **B. Issue Analyst** | Analyzes bug/task, scopes criteria, flags ambiguities | `IssueTask` | Diagnosis & Acceptance Plan | Scoped strictly to task payload |
| **C. Planner / Orchestrator** | Coordinates checkpoints, rollback points, task limits | `IssueTask` + Map | Staged Execution Plan (`PlanStep[]`) | Checkpoints hashed with tree SHA |
| **D. Autonomous Coding Agent** | Multi-file edits within scope in isolated workspace | Staged Plan | `ChangedFile[]` + Unified Diff | Restricted by path boundaries & allowlists |
| **E. Test Engineer** | Discovers and executes real test runners | Changed files | `TestResult` + `CommandExecution` | True exit codes, stdout, and durations |
| **F. DevGuard Security Analyst**| Scans for CWEs, hardcoded secrets, prompt injections | Patched diff | `SecurityFinding[]` | AST-level pattern matching |
| **G. Evidence Researcher** | Fetches official CVE/GHSA advisories via OSV/Tavily | Finding rules | `EvidenceItem[]` | Freshness timestamps, no hallucinations |
| **H. Causal Impact Agent** | Traces dependency topology and blast radius | Dependency graph | `ImpactHypothesis` | Directed acyclic traversal |
| **I. Independent Verifier** | Adversarial review in isolated fresh context | Full diff & tests | `VerifierFinding[]` + `VerifierVerdict` | Must not be coding agent; distinct checklist |
| **J. Repair Assurance** | Reconciles acceptance criteria vs real results | Test & Verifier results | `EvidenceManifest` | Validates hash consistency and residual risk |
| **K. UNWIND Governance Core** | Authorizes high-risk writes and warrant debits | `ApprovalRequest` | `GovernanceDecision` | Integer warrant ledger (`1,450 bp`) |
| **L. GitHub Delivery Agent** | Produces PR or local patch package | Signed Manifest | `PullRequestResult` | Real PR only if auth configured, else local patch |

---

## 2. Status Lifecycle & Invariants

```
INITIALIZING -> RUNNING -> AWAITING_APPROVAL (if high-risk) -> RUNNING -> READY_FOR_REVIEW
     |              |                 |                                         |
     v              v                 v                                         v
   FAILED        CANCELLED         BLOCKED                             Evidence Manifest Sealed
```

- **Invariant 1 (No Self-Verification):** The Coding Agent cannot verify its own code. The Independent Verifier runs with fresh context and a distinct adversarial checklist.
- **Invariant 2 (Diff Invalidation):** Any edit to the patch diff immediately invalidates previous test runs and verifier verdicts.
- **Invariant 3 (Truth in Delivery):** When GitHub credentials (`GITHUB_TOKEN`) are absent, the delivery status is explicitly marked `PR_NOT_CREATED_UNCONFIGURED` and a local unified diff patch is rendered.
- **Invariant 4 (UNWIND Single Authority):** High-risk writes debit the tenant's warrant ledger. If the balance is insufficient, the run is `BLOCKED`.
