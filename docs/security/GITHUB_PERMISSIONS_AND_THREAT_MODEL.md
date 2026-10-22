# AEGISNOVA — GitHub Permissions & Threat Model

**Platform:** AEGISNOVA  
**Tagline:** A New Standard for Safe AI  
**Scope:** GitHub Authentication, Autonomous Engineering Writes, Token Hygiene, and UNWIND Governance  
**Status:** IMPLEMENTED & AUDITED  

---

## 1. Principles of Least Privilege

AEGISNOVA operates under a zero-trust model for external code repositories and AI agent write capabilities:

1. **Tokens Never Leave the Server:**
   - `GITHUB_TOKEN` is resolved solely on the Next.js server via `process.env`.
   - Never sent in HTTP responses, never rendered into client DOM, never committed to disk, and never stored in `localStorage` or `sessionStorage`.
2. **Read-Only by Default:**
   - Unauthenticated users can audit public repositories and local demo fixtures without supplying credentials.
   - If `GITHUB_TOKEN` is unconfigured, the UI honestly renders `READ-ONLY PUBLIC / LOCAL DEMO`.
   - No mock "PR created" links or synthetic success banners are ever displayed without an authorized GitHub response.
3. **Bounded Patch Application:**
   - Autonomous Coding Agents work strictly inside isolated sandbox targets (`fixtures/demo-repos/` or ephemeral clone roots).
   - Edits are validated against file allowlists and AST syntax checkers before execution.
4. **Independent Adversarial Verification:**
   - In accordance with safety principles, the Autonomous Coding Agent is **prohibited from verifying its own output**.
   - An Independent Adversarial Verifier running in a separate, isolated evaluation context checks for prompt injection, hidden backdoors, and logic regressions.
5. **UNWIND Governance Authority:**
   - High-risk writes (pushing branches, opening pull requests) require human authorization or valid warrant balance debits (`-150 bp`).
   - Decisions are cryptographically bound to the SHA-256 evidence manifest hash.

---

## 2. Threat Analysis & Mitigations

| Threat | Description | AEGISNOVA Mitigation |
| :--- | :--- | :--- |
| **Token Exfiltration via Prompt Injection** | Malicious issue prompt instructs LLM to read environment variables or echo secrets in PR comments. | Server token isolation; static scanner filters `GITHUB_TOKEN`, `AKIA*`, and private key patterns from diffs and stdout before manifest sealing. |
| **Silent Regression / Broken Tests** | Autonomous agent introduces subtle functional bugs while attempting a fix. | Deterministic test runner execution (`python -m unittest`) is mandatory. Non-zero exit code halts pipeline at Stage 5. |
| **Self-Verification Bias** | Coding agent confirms its own code is safe without rigorous checks. | Separate Independent Verifier agent evaluates code in an isolated context using adversarial verification rules. |
| **Replay / Tampering of Evidence** | Attacker alters test results or security findings after run completion. | SHA-256 evidence manifest seal computed across test outputs, diff hash, verifier verdict, and UNWIND lineage hash. |
| **Rate Limit Lockout** | Unauthenticated public scans exhaust GitHub's 60 req/hr IP quota. | Pre-flight rate-limit header inspection (`x-ratelimit-remaining`); graceful fallback to local verified demo fixtures. |

---

## 3. GitHub App OAuth Scope Guidance

When deploying AEGISNOVA in enterprise production:
- **Recommended GitHub App Scopes:**
  - `Repository contents`: Read & Write (or Read-only for audit mode)
  - `Pull requests`: Read & Write
  - `Metadata`: Read-only
- **Unnecessary / Prohibited Scopes:**
  - `Admin`: NO
  - `Secrets`: NO
  - `Organization`: NO
