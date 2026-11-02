# AEGISNOVA Incident Response & Operational Runbooks

This document provides standardized standard operating procedures (SOPs) and runbooks for engineers responding to autonomous patrol alerts, circuit breaker trip conditions, and safe rollback triggers.

---

## Runbook 1: NightShift 3 AM Autonomous Patrol Alert

### Symptoms
- Autonomous patrol flags a high or critical vulnerability during out-of-hours inspection.
- NightShift generates an automated pull request with `[NIGHTSHIFT-AUTONOMOUS]` header.

### Assessment Procedure
1. **Verify Evidence Chain**: Open the associated PR and inspect the Tavily CVE Evidence Manifest citations.
2. **Review AST Blast Radius**: Check the Causal Impact section to confirm impacted modules are confined to the targeted service.
3. **Inspect Verifier Results**: Confirm that both unit tests and integration smoke tests passed with zero regressions.

### Action Matrix
- **Confidence > 95% & Blast Radius = Low**: Allow automated merge via dual-autonomy policy if human escalation threshold is not triggered.
- **Confidence < 95% or Impacted Scope > 3 Modules**: Gate PR under human approval queue; notify on-call engineering lead.

---

## Runbook 2: Circuit Breaker Tripping & Safety Lockdown

### Symptoms
- Consecutive build failures (> 3 attempts) during autonomous repair synthesis.
- Rate limit exhausted on external intelligence APIs (GitHub or Tavily).

### Resolution Steps
1. **Halt Autonomous Patrol Loop**:
   ```bash
   node scripts/copilot-cli.js --mode status
   ```
2. **Review Audit Logs**:
   Inspect recent activity in the Audit page or query `GET /api/engineering/status`.
3. **Reset Circuit Breaker**:
   Once underlying service stability is verified, clear the quarantine flag via the Settings dashboard.

---

## Runbook 3: Emergency Automated Rollback

### Trigger Conditions
- Post-merge regression detected in production smoke checks.
- Unexpected service degraded status reported by telemetry.

### Rollback Execution
1. Revert target commit on `main` using standard Git revert:
   ```bash
   git revert -m 1 <COMMIT_SHA> -m "revert: rollback unexpected autonomous patch regression"
   git push origin main
   ```
2. Tag incident in AEGISNOVA memory to prevent recurrent proposal of the same patch signature.
3. Review post-mortem log in `docs/` and add regression test coverage to `scripts/test-runner.js`.
