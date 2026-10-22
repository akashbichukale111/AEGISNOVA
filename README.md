# AEGISNOVA — A New Standard for Safe AI
### Autonomous AI Software Engineering with Verifiable Trust & Governed Operations
**Built for the Nebius × NVIDIA Global AI Hackathon**

[![Smoke & Contract Tests](https://img.shields.io/badge/Smoke%20Tests-87%2F87%20Passing-brightgreen?style=for-the-badge&logo=githubactions)](https://github.com/akashbichukale111/AEGISNOVA)
[![Platform Architecture](https://img.shields.io/badge/Architecture-12--Stage%20PCPR%20Multi--Agent-00D4FF?style=for-the-badge&logo=diagramsdotnet)](https://github.com/akashbichukale111/AEGISNOVA)
[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA%20NIM-Hopper%20GH100%20%7C%20Nemotron--4--340B-76B900?style=for-the-badge&logo=nvidia)](https://github.com/akashbichukale111/AEGISNOVA)
[![UNWIND Governance](https://img.shields.io/badge/Governance-UNWIND%20Decaying%20Warrant-6366F1?style=for-the-badge)](https://github.com/akashbichukale111/AEGISNOVA)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

```
    ___    ______ _____ _____ _____   __  ______ _    _____ 
   /   |  / ____// ___//_  _// ___/  / / / / __ \ |  / /   |
  / /| | / __/  / / __  / /  \__ \  / / / / / / / | / / /| |
 / ___ |/ /___ / /_/ /_/ /  ___/ / / /_/ / /_/ /| |/ / ___ |
/_/  |_/_____/ \____//___/ /____/  \____/\____/ |___/_/  |_|
```

> **Canonical Product Vision:** One product, one coherent navigation, one enterprise design system, and a verifiable execution fabric. AEGISNOVA replaces disjointed AI coding assistants with an autonomous software engineer that provides cryptographic proof of correctness, independent adversarial verification, and bounded governance authority before any code touches production.

---

## 🌟 Executive Overview & Hackathon Submission

AEGISNOVA is an end-to-end autonomous software engineering and governed operations platform. Unlike conventional coding assistants that propose unverified snippets or evaluate their own outputs, AEGISNOVA guarantees that every change is:
1. **Discovered via Real AST & Manifest Intelligence (Mode A):** Full repository map, language composition, entry points, test runners, and dependency vulnerability hypotheses with exact file paths and line numbers.
2. **Turned into Autonomous Tasks in One Click:** Direct bridge from diagnostic finding to repair loop.
3. **Executed through a 12-Stage Verifiable Pipeline (Mode B):** Bounded edits powered by NVIDIA NIM (`Nemotron-4-340B`, `Llama-3.1-405B`).
4. **Proven via Deterministic Test Execution:** Discovers and executes local unit test suites (`python -m unittest`, `npm test`), capturing exit codes, durations, stdout, and stderr.
5. **Audited by DevGuard AI:** Deep static vulnerability and hardcoded secret scanning.
6. **Independently Verified (Adversarial Verifier):** Separate evaluator in a fresh context specifically designed to prevent LLM self-verification bias.
7. **Authorized by UNWIND Governance Core:** Warrant ledger debits (`-150 bp`) and immutable decision lineage hashes.
8. **Sealed into a Proof-Carrying Pull Request (PCPR):** SHA-256 evidence package containing all telemetry, test outputs, and security receipts.

---

## 🏗️ Architecture & Dual-Mode Workflow

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

### The 12-Stage PCPR Verification Pipeline

| Stage | Name | Agent Role | Verifiable Artifact |
| :---: | :--- | :--- | :--- |
| **01** | Repository Architecture Intake | `Repository Intelligence` | Language breakdown, entry points, test runner discovery |
| **02** | Issue Diagnosis & Scoping | `Issue Analyst` | Root-cause analysis & acceptance criteria bounding |
| **03** | Staged Risk Decomposition | `Planner / Orchestrator` | Rollback checkpoint & blast-radius boundary |
| **04** | Autonomous Patch Synthesis | `Autonomous Coding Agent` | Unified diff synthesized via NVIDIA NIM |
| **05** | Real Test Execution Loop | `Test Engineer` | Deterministic unit test execution proof (`exitCode: 0`) |
| **06** | DevGuard Security Scan | `DevGuard Security Analyst` | Zero secret leaks, AST vulnerability validation |
| **07** | Evidence Advisory Reconciliation | `Evidence Researcher` | CVE advisory lookup & vulnerability score checks |
| **08** | Causal Impact Analysis | `Causal Impact Agent` | Downstream module blast radius graph |
| **09** | Independent Adversarial Verification | `Independent Verifier` | Fresh-context review (Anti-Self-Verification) |
| **10** | Repair Assurance Manifest Seal | `Repair Assurance` | SHA-256 root hash of the entire evidence package |
| **11** | UNWIND Governance Gate | `UNWIND Governance Core` | Decaying warrant debit (`-150 bp`) & lineage hash |
| **12** | GitHub Delivery / Local Patch | `GitHub Delivery Agent` | Authenticated PR or honest `LOCAL_PATCH_ONLY` package |

---

## 🧭 Platform Surface & Navigation Map

| Module | Route | Underlying Engine | State |
| :--- | :--- | :--- | :--- |
| **Autonomous Engineering Studio** | `/engineering` | 12-Stage PCPR Engine + GitHub Client + Mode A Audit | **LIVE / VERIFIED** |
| **NightShift SDE** | `/nightshift` | Python SDE Daemon (`port 8787`) | **CONNECTED** |
| **Autonomous Operations** | `/operations` | Python Operations Service (`port 8080`) | **CONNECTED** |
| **Security Center** | `/security` | DevGuard AI Scanner, Fixer & Validator | **LIVE** |
| **Governance Core** | `/governance` | UNWIND Decaying Warrant Ledger & Human Countersign | **CONNECTED** |
| **Evidence Intelligence** | `/evidence` | Evidence advisory graph & citation matrix | **PREVIEW** |
| **Causal Impact** | `/causal-impact` | Blast-radius dependency graph | **PREVIEW** |
| **Repair Assurance** | `/repair-assurance` | Cryptographic assertion verifier | **PREVIEW** |
| **Audit & Observability** | `/audit` | Correlated trace timeline & SRE circuit breakers | **LIVE** |
| **Settings & Integrations** | `/settings` | 8-module health registry & token security posture | **LIVE** |

---

## ⚡ Quick Start Guide

### Prerequisites
- **Node.js**: v18+ (tested on Node v24.18.0)
- **Python**: 3.10+ (tested on Python 3.13)
- **Git**: Installed and configured

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/akashbichukale111/AEGISNOVA.git
cd AEGISNOVA

# Install frontend dependencies
npm install

# (Optional) Setup environment variables
cp .env.example .env
```

### 2. Run Automated Verification Suite
```bash
npm test
```
*Executes 87 automated smoke checks verifying contracts, API routes, security boundaries, and token hygiene with 0 failures.*

### 3. Start Backend Services (Multi-Process Local Mode)

#### Terminal 1 — Autonomous Operations Backend
```bash
cd services/autonomous-operations
python -m aegisnova_ops
```
*Listens on `http://127.0.0.1:8080` (SQLite queue, state machine, webhook proxy).*

#### Terminal 2 — NightShift SDE Daemon
```bash
cd services/nightshift-sde
python -m nightshift serve
```
*Listens on `http://127.0.0.1:8787` (local workspace worker daemon).*

#### Terminal 3 — AEGISNOVA Web Application
```bash
npm run build
npm start
```
*Open **[http://localhost:3000](http://localhost:3000)** in your browser.*

---

## 🔒 Security Posture & Threat Model

1. **Tokens Never Leave the Server:** `GITHUB_TOKEN`, `NVIDIA_API_KEY`, and `NEBIUS_API_KEY` are read exclusively on the server side (`process.env`). They are never exposed in client responses, HTML source, browser storage, or exported manifests.
2. **Honest Authentication Boundaries:** If `GITHUB_TOKEN` is unconfigured, the UI explicitly displays `READ-ONLY PUBLIC / LOCAL DEMO`. No synthetic fake PR links or fabricated delivery states are generated.
3. **No Self-Verification:** The autonomous coding agent cannot verify its own code. An Independent Adversarial Verifier evaluates diffs in a separate context for regressions, prompt injection, and unauthorized writes.
4. **UNWIND Governance Authority:** High-consequence code changes require explicit warrant authorization (`-150 bp`) and human countersignature.

---

## 👥 Authors & Contributors

**AEGISNOVA Engineering Team**  
- **Akash Bichukale** ([@akashbichukale111](https://github.com/akashbichukale111)) — Platform Architecture, Autonomous Engineering, and Integration Lead.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — see the LICENSE file for details. Built upon the open foundation of DevGuard AI, DevGuard Enterprise, and UNWIND Governance Core.
