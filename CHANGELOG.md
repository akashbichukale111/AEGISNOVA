# Changelog

All notable changes to the AEGISNOVA platform are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-11-02

### Added
- **Production Deployment Guide**: Comprehensive containerization, multi-stage Dockerfile, and reverse proxy guidelines in `docs/DEPLOYMENT.md`.
- **Operational Runbooks**: Standard incident response, 3 AM patrol triage, and emergency rollback procedures in `docs/RUNBOOKS.md`.
- **Telemetry & Health Observability**: Introduced `src/lib/observability/metrics.ts` for real-time latency percentile collection and health counters.
- **Autonomous Patch Validator**: Added `src/lib/autonomous-engineering/patch-validator.ts` for pre-PR diff AST sanity checks and prohibited pattern filtering.
- **Expanded CI Pipeline**: Added automated TypeScript type verification and contract check stages in `.github/workflows/ci.yml`.
- **Enhanced Test Runner**: Expanded verification suite to 116+ automated smoke and governance checks.

---

## [1.0.0] - 2026-11-01

### Added
- **Interactive Engineering Copilot**: Embedded conversational UI & NightShift 3 AM dual-autonomy engineering agent.
- **Standalone Copilot CLI**: Terminal-driven workflow runner under `scripts/copilot-cli.js`.
- **Tavily Live Search Integration**: Real-time CVE reconciliation and external evidence verification.
- **Unified Governance Architecture**: Complete governance specifications and architectural blueprints.
- **Automated Verification Suite**: Initial smoke test suite and CI workflow running across pull requests.
- **Open Source Foundations**: Added code of conduct, contribution guidelines, and security baseline.
