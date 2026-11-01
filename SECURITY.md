# Security Policy

## Supported Versions

AEGISNOVA takes the security of autonomous software engineering and governed operations seriously.

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## Autonomous Safety & Cryptographic Boundaries

AEGISNOVA enforces three non-negotiable security boundaries:

1. **Separation of Duties (Anti-Self-Verification):**
   An AI agent proposing or synthesizing a code patch is never permitted to independently verify or countersign its own change. Verification is executed by a separate adversarial verifier in an isolated context.

2. **UNWIND Decaying Governance Warrants:**
   All write-capable actions (repository mutations, PR creation, cloud deployments) require cryptographic warrant authorization. Warrants decay over time (`-150 bp`) and require human renewal.

3. **Deterministic Sandbox Isolation:**
   Code execution and test suites run in sandboxed child processes with bounded timeouts and CPU quotas.

---

## Reporting a Vulnerability

If you discover a security vulnerability within AEGISNOVA, please follow responsible disclosure practices:

1. **Do not create a public issue:** Please do not open a public GitHub issue for sensitive vulnerabilities.
2. **Contact Maintainers:** Email security reports to `akashbichukale111@gmail.com` with:
   - Description of the vulnerability.
   - Proof of Concept (PoC) or reproducible steps.
   - Potential impact on the UNWIND warrant ledger or autonomous execution pipeline.
3. **Response Timeline:** We will acknowledge receipt of your vulnerability report within 24 hours and provide an estimated timeline for remediation.
