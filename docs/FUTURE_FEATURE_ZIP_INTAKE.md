# AEGISNOVA Future Feature ZIP Intake Plan & Checklist
**Product:** AEGISNOVA  
**Scope:** Strict verification and ingestion protocols for the five upcoming feature ZIPs.

---

## 1. Safety Principles for External Archive Ingestion

When the user supplies the upcoming ZIP archives in later phases, **never execute scripts blindly or extract archives directly into live production paths**.

The ingestion of each ZIP must adhere to the **Four Gates of Ingestion**:
1. **Gate 1: Static Pre-Extraction Inspection:** Inspect archive manifests, file lists, and sizes without extracting executable scripts to the system root.
2. **Gate 2: Quarantine & Security Audit:** Extract to an isolated `quarantine/` sandbox. Scan for hardcoded API keys, private certificates, compiled binaries (`.exe`, `.so`, `.dll`), and suspicious package install hooks (`postinstall`).
3. **Gate 3: Contract Conformance Check:** Verify that entry points and exported data structures conform to AEGISNOVA versioned contracts (`src/contracts/index.ts`).
4. **Gate 4: Feature-Flagged Wiring:** Mount the module behind a feature flag (e.g. `FEATURE_NIGHTSHIFT_ENABLED=false`). Enable only after regression tests pass.

---

## 2. Universal Intake Checklist (Per Archive)

For **every** incoming ZIP file, verify and complete:

- [ ] **1. Archive Integrity:** Verify checksum and uncorrupted extraction.
- [ ] **2. Dependency Manifest Inspection:** Check `package.json`, `pyproject.toml`, or `requirements.txt` for pinned, safe versions.
- [ ] **3. Secrets Audit:** Verify zero hardcoded keys, bearer tokens, or `.env` files with production values.
- [ ] **4. Execution Safety:** Confirm no untrusted code execution on the local host. Sandbox any dynamic tests.
- [ ] **5. Schema Conformance:** Map module inputs and outputs to AEGISNOVA canonical contracts (`src/contracts/index.ts`).
- [ ] **6. Governance Alignment:** Verify all high-risk actions route through UNWIND authority gates.
- [ ] **7. Unit Testing:** Run module-specific unit tests in isolation before UI wiring.
- [ ] **8. Integration Status Update:** Transition module in `src/lib/demo-data.ts` and `src/app/settings/page.tsx` from `PLANNED` to `CONNECTED` (or `VERIFIED`).
- [ ] **9. Rollback Point:** Create a clean git commit or tag before merging each feature.

---

## 3. Module-Specific Intake Specifications

### Feature 01: NightShift SDE
- **Role:** Autonomous off-hours repository engineering, durable jobs, checkpoints, watchdog, and recovery.
- **Expected Files:** `nightshift_runner.py`, `watchdog.py`, `checkpoint_store.py`, `job_scheduler.py`.
- **Target Schema:** `WorkflowRun` (`src/contracts/index.ts`).
- **Governance Gate:** NightShift MUST respect UNWIND workspace scopes. It is prohibited from pushing commits directly to default branches without human countersignatures.
- **Verification Command:** `pytest tests/test_nightshift_isolation.py`.

### Feature 02: Evidence Intelligence
- **Role:** Deterministic vulnerability intelligence, OSV/GHSA adapters, source reconciliation, freshness, and conflict detection.
- **Expected Files:** `evidence_engine.py`, `osv_client.py`, `ghsa_adapter.py`, `citation_reconciler.py`.
- **Target Schema:** `EvidenceReference` (`src/contracts/index.ts`).
- **Safety Boundary:** The rule *“no result does not mean safe”* must be enforced in the UI. Fall back to cached corpora if rate-limited.
- **Verification Command:** `pytest tests/test_evidence_reconciliation.py`.

### Feature 03: Causal Impact Intelligence
- **Role:** Dependency graph traversal, explainable root-cause hypotheses, downstream blast radius, and counterfactual modeling.
- **Expected Files:** `causal_graph.py`, `counterfactual_engine.py`, `hypothesis_ranker.py`.
- **Target Schema:** `ImpactAnalysis` (`src/contracts/index.ts`).
- **Safety Boundary:** Graph reachability alone must never be displayed as causal proof. Uncertainty bands (`LOW`, `MODERATE`, `HIGH`) must be computed and visualized.
- **Verification Command:** `pytest tests/test_causal_counterfactuals.py`.

### Feature 04: Independent Repair Assurance
- **Role:** Independent patch verification, Patch Breaker adversarial testing, test evidence, residual risk proof, and warranty certification.
- **Expected Files:** `patch_breaker.py`, `warranty_verifier.py`, `proof_attester.py`.
- **Target Schema:** `RepairProof` (`src/contracts/index.ts`).
- **Safety Boundary:** The repair generator (DevGuard AI Fixer) must **never** certify its own repairs. Independent execution in a sandboxed container is required.
- **Verification Command:** `pytest tests/test_patch_breaker_adversarial.py`.

### Feature 05: Autonomous Operations & Notifications
- **Role:** Workflow orchestration, approval wait/resume, SNS email/SMS, official WhatsApp Cloud alerts, and CloudWatch alarms.
- **Expected Files:** `orchestrator.py`, `sns_adapter.py`, `whatsapp_client.py`, `dlq_monitor.py`.
- **Target Schema:** `NotificationStatus` (`src/contracts/index.ts`).
- **Safety Boundary:** No real notifications may be dispatched or AWS charges incurred during local development without explicit authorization.
- **Verification Command:** `pytest tests/test_notification_mock_dispatch.py`.
