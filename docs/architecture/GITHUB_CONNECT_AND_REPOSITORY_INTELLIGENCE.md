# AEGISNOVA — GitHub Connection & Repository Intelligence Architecture

**Platform:** AEGISNOVA  
**Tagline:** A New Standard for Safe AI  
**Hackathon:** Nebius × NVIDIA Global AI Hackathon  
**Module:** Workstream 01 (NightShift SDE) & Proof-Carrying Pull Requests (PCPR)  
**Status:** IMPLEMENTED & VERIFIED  

---

## 1. Overview & Dual-Mode Philosophy

AEGISNOVA introduces a dual-mode workflow for autonomous repository engineering that guarantees safety, determinism, and full evidence provenance before any code can be delivered or merged.

```
+-----------------------------------------------------------------------------------------+
|                                 AEGISNOVA CONTROL PLANE                                 |
+-----------------------------------------------------------------------------------------+
                                           |
                   +-----------------------+-----------------------+
                   |                                               |
                   v                                               v
        [ MODE A: AUDIT & MAP ]                       [ MODE B: BUILD & REPAIR ]
      - Repository Intake (URL/Slug)                 - Natural Language Task Specification
      - AST & Manifest Scanning                      - Bounded Patch Synthesis (NVIDIA NIM)
      - Dependency Graph Extraction                  - Deterministic Test Harness Loop
      - Discovered Entrypoints/Runners               - DevGuard Static Security Audit
      - Vulnerability & Defect Hypotheses            - Independent Adversarial Verifier
                   |                                 - UNWIND Governance Warrant Gate
                   |                                 - SHA-256 Proof-Carrying PR Seal
                   +------> [ Turn into Task ] ----->+
```

### 1.1 Mode A: Repository Intelligence & Audit
Allows operators to connect an authorized GitHub repository or supply a repository URL (or local fixture shorthand such as `demo/payments-service`), automatically discovering:
- **Language Composition:** Real byte-weighted language detection across Python, JavaScript, TypeScript, Shell, YAML, etc.
- **Entry Points:** Discovers server and module entry points (`app/__init__.py`, `service.py`, `main.py`, `index.js`).
- **Test Runners:** Detects unittest, pytest, vitest, and jest setups.
- **Manifests & Dependencies:** Extracts package declarations from `requirements.txt` and `package.json`, auditing for unpinned packages, supply-chain vulnerabilities, and deprecated ciphers.
- **Evidence-Backed Findings:** Maps exact file paths, line numbers, and code snippets to standard security rules (`CWE-89`, `CWE-798`, `CVE-2026-8812`, `TEST-COVERAGE-DEFICIT`), with recommended remediations and test assertions.
- **One-Click Hand-off:** Operators click **"Turn into Autonomous Task"** to immediately switch to Mode B with all diagnostic context pre-filled.

### 1.2 Mode B: Autonomous Build & Repair (Proof-Carrying PRs)
Executes a 12-stage autonomous pipeline:
1. **Repository Intake & Baseline Verification:** Validates clean working tree and tests.
2. **Issue Diagnosis & Acceptance Scoping:** Bounded scoping of the required fix.
3. **Staged Checkpoint & Risk Decomposition:** Establishes rollbacks and blast radius limits.
4. **Autonomous Patch Synthesis:** Synthesized using NVIDIA NIM (Nemotron-4-340B / Llama-3.1-Nemotron-70B).
5. **Real Test Execution Loop:** Runs real local test runner (`python -m unittest discover -s tests`). Captures exit code, duration, stdout, and stderr.
6. **DevGuard Security Audit:** Inspects unified diff for newly introduced vulnerabilities or secrets.
7. **Multi-Source Evidence Advisory:** Aggregates CVE advisories, NIST metrics, and benchmark logs.
8. **Causal Blast Radius Analysis:** Analyzes downstream module impact.
9. **Independent Adversarial Verifier:** Evaluates the patch in a fresh, isolated context (strictly preventing self-verification).
10. **Repair Assurance & Manifest Seal:** Generates SHA-256 evidence manifest hash.
11. **UNWIND Governance Lease:** Debits warrant balance (`-150 bp`) and creates an immutable lineage hash.
12. **GitHub Delivery:** Generates git branch and PR if authorized, or creates a sealed local patch with the evidence package if read-only.

---

## 2. API Contract Specifications

### 2.1 `/api/github/status`
- **GET:** Returns `{ status: "CONNECTED" | "UNCONFIGURED" | "RATE_LIMITED", tokenConfigured: boolean, username?: string, scopes?: string[] }`.
- **POST:** Accepts `{ url: string }`. Verifies repository accessibility, branch information, and push/pull permissions.

### 2.2 `/api/github/repos`
- **GET:** Returns available repository targets (local demo fixtures + authorized remote repositories).

### 2.3 `/api/repo-intelligence/audit`
- **POST:** Accepts `{ url: string }` or `{ repoTargetId: string }`. Returns `RepoAuditReport` adhering to schema v1.0.0.

### 2.4 `/api/engineering/run`
- **POST:** Accepts `{ repoTarget, issueTask, nvidiaApiKey?, nebiusApiKey? }`. Spawns the 12-stage autonomous execution runner.
- **GET:** Returns list of active and completed runs.

### 2.5 `/api/engineering/status`
- **GET:** Accepts `?runId=...`. Returns live step progression, terminal events, and sealed manifest.

---

## 3. Cryptographic Evidence Integrity

Every run generates an `EvidenceManifest` sealed with a SHA-256 hash across all 14 evidence vectors:
```typescript
manifestHash = sha256(
  runId + repoId + diffHash + testResults.stdout + verifierVerdict + lineageHash
)
```
This guarantees that no pull request can be accepted without cryptographically verifiable proof of tests passed, security scans cleared, independent verification approved, and UNWIND governance authorized.
