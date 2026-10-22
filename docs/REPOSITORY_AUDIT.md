# AEGISNOVA Upstream Repository Audit
**Generated:** October 20, 2026  
**Auditor:** Principal Product Architect & Integration Lead  
**Scope:** Three canonical upstream repositories inspected locally from verified archives and remote git references.

---

## 1. Executive Summary & Verification Ledger

| Metric | Repository 1: DevGuard AI | Repository 2: DevGuard Enterprise | Repository 3: UNWIND |
| :--- | :--- | :--- | :--- |
| **Verified URL** | `https://github.com/akashbichukale111/devguard-ai` | `https://github.com/akashbichukale111/DevGuard-Enterprise` | `https://github.com/akashbichukale111/unwind-live-verified` |
| **Default Branch** | `main` | `main` | `main` |
| **Verified Remote HEAD** | `17b5fb2240b885052f7a4a20793c5f7978e6fc90` | `46a0aa2ff1102a737781c78f0c4bea4203769265` | `36b75e0ea11a5c1b12018046d5002f36af6017c7` |
| **License** | Apache 2.0 (inferred/shared) | Apache 2.0 (`LICENSE` verified) | Custom Open / Permissive (GCP ADK) |
| **Primary Frontend** | Next.js (App Router) + Tailwind | Next.js (App Router) + Tailwind + Monaco | Next.js + Static Replay Assets |
| **Primary Backend** | FastAPI (Python 3.11+) | FastAPI (Python 3.11+) + Proofpack v2 | Python (>=3.12, Google ADK 2.6.3) |
| **Primary Role in AEGISNOVA** | Scanner, Fixer, Validator Engine | Enterprise Command Center UX & Panels | Universal Governance & Warrant Core |

---

## 2. Repository 1: DevGuard AI

### 2.1 Stack & Entry Points
- **Backend:** FastAPI application (`backend/main.py`), OpenTelemetry instrumentation (`opentelemetry.instrumentation.fastapi`, `LoggingInstrumentor`), Redis caching (`backend/core/cache.py`), resilience circuit breaker (`backend/core/resilience.py`).
- **Endpoints:**
  - `POST /scan`: Initiates vulnerability scanning pipeline, trace continuation (`traceparent`), approval gate pausing for Critical/High findings, and append-only audit chain emission.
  - `GET /metrics`: Prometheus/SigNoz OpenTelemetry metric export.
  - `WS /ws`: WebSocket live progress streaming.
  - `/god-mode/*`: SRE fault injection and simulation endpoints.
- **Frontend:** Next.js with App Router:
  - `/` (Dashboard / Landing)
  - `/scanner` (Code scan trigger and intake)
  - `/result` (Scan outcome and trace waterfall)
  - `/nexus` (Commander, FinOps, LLM Judge panels)

### 2.2 Functional Behavior vs. Replay
- The FastAPI `/scan` pipeline contains genuine AST analysis logic, regex vulnerability rules, and circuit breaker protection.
- The frontend features an interactive WebSocket client (`useScanSocket.ts`) and trace waterfall visualizer (`TraceWaterfall.tsx`).
- Fallback paths are implemented when Groq or Redis are unreachable, ensuring zero hard crashes (returns 503 with `trace_id` rather than 500).

### 2.3 Tests & Verification
- **Test Commands:** `python -m pytest tests/` and `python scripts/load_test.py`.
- **Benchmark:** `backend/core/benchmark.py` measures latency, cache hit ratios, and token costs.

### 2.4 Security & Secrets Exposure Check
- Scanned `frontend/.env.local`: Found only ephemeral GitHub Codespaces forwarding URLs (`https://super-system-*-8001.app.github.dev`). No private keys, AWS credentials, or hardcoded cloud secrets were discovered.
- Recommended Remediation: Ensure ephemeral Codespaces URLs are replaced with standard localhost variables in `.env.example`.

---

## 3. Repository 2: DevGuard Enterprise

### 3.1 Stack & Entry Points
- **Backend:** FastAPI v2 orchestration (`backend/v2/`):
  - `proofpack.py`: Cryptographic proof packaging for replay runs.
  - `replay.py`: Deterministic zero-infrastructure replay runner (`--replay <run-id>`).
  - `evidence.py` & `faults.py`: Enterprise failure mode evaluation.
  - `ml_impact.py`: ML pipeline blast radius and downstream dependency impact assessment.
  - `handoff.py`: Enterprise ticketing and notification handoff contracts.
- **Frontend:** Next.js (App Router) + Tailwind CSS + Lucide Icons + Monaco Editor:
  - `/command`: DevGuard Command Center (`IncidentHeader`, `EvidenceLedger`, `BlastRadiusPanel`, `PolicyApproval`, `RootCause`, `SecurityMetrics`, `WriteBack`).
  - `/nexus`: Enterprise AI governance and FinOps metrics.
  - `/scanner`: Project code scanner surface.

### 3.2 Functional Behavior vs. Replay
- `/command/page.tsx` was specifically designed to run in zero-infrastructure replay mode from static JSON bundles (`public/replay/manifest.json`), eliminating external database or LLM dependencies for demonstration purposes.
- Real underlying algorithms exist in `backend/v2/ml_impact.py` and `backend/v2/proofpack.py`.

### 3.3 Tests & Verification
- **Test Suite:** Over 50 unit and integration tests located in `tests/`:
  - `test_audit_chain.py`: Proves hash-linked audit integrity.
  - `test_approval_gate.py`: Proves high-risk mutations are blocked without human approval.
  - `test_circuit_breaker.py`: Verifies circuit breaker tripping and recovery.
  - `test_evidence_contract.py`: Validates evidence schema serialization.

### 3.4 Security & Secrets Exposure Check
- Scanned repository root and frontend: Verified clean `.env.example` with placeholders only. No exposed production secrets.

---

## 4. Repository 3: UNWIND (unwind-live-verified)

### 4.1 Stack & Entry Points
- **Architecture:** Retractable Decisions platform built on Python (>=3.12) and Google ADK 2.6.3 (`pyproject.toml`).
- **Core Principle:** Tiered evaluation:
  - **T0 (Zero Model):** Blast-radius traversal over reverse index (deterministic graph traversal, 0 model calls).
  - **T1 (Zero Model):** Arithmetic materiality filter (`shock > slack`, pure subtraction, 0 model calls).
  - **T2 (Model Tier):** Ambiguous arbitration, drafting, and prose generation (Vertex AI Gemini).
  - Guaranteed outage survival: `UNWIND_VERTEX_DISABLED=1` isolates T0/T1 completely from model client failures.
- **Governance & Authority Module (`warrant/ledger.py`):**
  - Deterministic, decaying, capability-scoped authority ledger.
  - Minted solely from countersigned human outcomes; debited on every delegated act.
  - Pure integer fold (`fold_balance`): touched no clock, no network, no floating point.

### 4.2 Reusable Governance Modules
- `warrant/ledger.py`: Pure integer authority fold and capability leasing.
- `court/protocol.py` & `court/arbiter.py`: Human-in-the-loop escalation and countersignature contracts.
- `settle/loadrating.py`: Source standing and claim reliability scoring.
- `lib/schema.py`: Temporal Truth schema (`valid_from`, `invalidated_at`, `invalidation_reason`, `authority_scope`).

### 4.3 Tests & Verification
- **Test Suite:** Comprehensive test suite in `tests/` with 249 passed unit tests.
- **Zero-Model Tests:** `test_warrant_zero_model.py`, `test_zero_model.py`, and `test_tower_zero_model.py` assert via AST import-graph walking that no model clients are imported into deterministic paths.

### 4.4 Security & Secrets Exposure Check
- Verified clean. GCP credentials and Firebase configurations utilize emulator environment variables (`FIRESTORE_EMULATOR_HOST`, `PUBSUB_EMULATOR_HOST`).

---

## 5. Candidate Components for AEGISNOVA Reuse

1. **Design System & Visual Canvas:** DevGuard Enterprise's command-center layout patterns, metric card styling, and dark theme palette.
2. **Scanner / Fixer / Validator Engine:** DevGuard AI's FastAPI core and circuit breaker resilience layer.
3. **Common Governance Core:** UNWIND's deterministic warrant ledger and human approval protocol.
4. **Impact Topology:** DevGuard Enterprise's blast radius visualization combined with UNWIND's T0 graph traversal concepts.
