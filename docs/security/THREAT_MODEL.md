# AEGISNOVA — Security Architecture & Threat Model

**Signature Feature:** Proof-Carrying Pull Requests (PCPR)  
**Standard:** Enterprise Application Security & Autonomous Agent Containment  

---

## 1. Threat Vectors & Defense Boundaries

| Threat Vector | Description | AEGISNOVA Mitigation Boundary |
|---|---|---|
| **Prompt Injection via Issue / Repo Content** | Attackers craft issues or README files with malicious instruction injection. | All external issue text, markdown, and repo comments are treated as **untrusted data**, not system instructions. |
| **Rogue Code Synthesis / Hallucination** | LLM generates vulnerable or malicious code in patches. | **Independent Adversarial Verifier** evaluates diff in a separate, isolated context with distinct checklist. Must pass real deterministic tests and DevGuard AST scans. |
| **Self-Verification Bypass** | Agent acts as its own reviewer and approves its own code. | **Prohibited by architectural invariant.** The Autonomous Coding Agent cannot issue verification verdicts or sign off on repairs. |
| **Unauthorized Consequential Writes** | Autonomous agent pushes directly to production branches. | **UNWIND Governance Gate.** Consequential mutations strictly require human countersignature and debit an integer warrant ledger (`1,450 bp`). Direct push to `main` is blocked. |
| **Secret Leakage in Patches or Logs** | Hardcoded API keys or credentials committed to source. | Automated pre-commit and post-synthesis **secret scanner** redacts keys and fails closed if high-entropy tokens are detected. |
| **Path Traversal Escape** | Malicious patch attempts writes outside sandbox workspace. | Strict path boundary enforcement: all edits must resolve within the isolated repository target directory. |
| **Denial of Service / Runaway Loops** | Agent enters infinite retry loop consuming resources. | Bounded attempt budget (maximum 3 repair cycles), wall-clock timeouts, and cooperative cancellation tokens. |

---

## 2. UNWIND Governance Authority Model

1. **Deterministic Warrant Ledger:** Authority balances are pure integer basis points (e.g. `1,450 bp`). No floating-point rounding errors exist.
2. **Zero-Model Guarantee:** Authority evaluation does not depend on LLM inference. External model outages cannot prevent or corrupt governance decisions.
3. **Lineage Hashing:** Every approved action is tied to the SHA-256 hash of the evidence manifest, preventing cross-run replay attacks.
