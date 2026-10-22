# AEGISNOVA — 2-Minute Hackathon Demo Script
**Event:** Nebius × NVIDIA Global AI Hackathon  
**Feature Highlight:** Proof-Carrying Pull Requests (PCPR)  

---

## 1. Setup & Starting State (Before Presentation)
1. Verify background daemons are active:
   - Port 8080: Autonomous Operations
   - Port 8787: NightShift SDE
   - Port 3000: Next.js Command Center
2. Open your browser to `http://localhost:3000/engineering`.

---

## 2. Live Demo Script (Step-by-Step)

### Step 1: Context & Problem Statement (0:00 - 0:30)
- *"Autonomous AI coding agents today suffer from a critical flaw: they review their own code, invent test results, and push unverified changes to GitHub."*
- *"AEGISNOVA introduces **Proof-Carrying Pull Requests**: an autonomous engineering pipeline where code is accompanied by verifiable, traceable proof—real command executions, DevGuard AST scans, independent adversarial verification, and UNWIND governance."*

### Step 2: Triggering the Pipeline (0:30 - 1:00)
- In the **Proof-Carrying PR Studio** (`/engineering`):
  - Select target repository: `demo/payments-service`
  - Select mode: `PATCH_AND_VERIFY`
  - Click **"Execute Proof-Carrying Run"**.
- Point out the **12-Stage Execution Stepper**:
  - Show *Repository Intelligence* discovering real manifests (`requirements.txt`).
  - Show *Issue Analyst* scoping criteria for SQL parameter binding.
  - Show *Autonomous Coding Agent* synthesizing the minimal AST patch using **NVIDIA NIM (Nemotron-4-340B)**.

### Step 3: Verifiable Proof & Independent Verification (1:00 - 1:30)
- Scroll to the **Real Test Execution Proof**:
  - Show exact command executed: `python -m unittest discover -s tests`.
  - Show exit code: `0` with real execution time (`340ms`).
- Highlight the **Independent Verifier Panel**:
  - Explain that the verifier runs in a *separate context* with a distinct adversarial checklist.
  - Show Verdict: `PASS`.
- Highlight **UNWIND Governance Core**:
  - Show human countersignature gate and `-150 bp` warrant debit from the `1,450 bp` ledger.

### Step 4: The Proof-Carrying Manifest Package (1:30 - 2:00)
- Reveal the sealed **Evidence Manifest** with SHA-256 hash.
- Click **"Export Markdown"** or **"Export JSON"** to demonstrate how the tamper-evident package is submitted to human reviewers.
- Point out the honest delivery status: `PR_NOT_CREATED_UNCONFIGURED [LOCAL DEMO]` because no GitHub token is provided—zero fake PR URLs.
