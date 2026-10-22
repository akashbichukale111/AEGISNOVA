# AEGISNOVA — Known Limitations & Operational Boundaries

**Evaluation Standard:** Truth in Advertising  
**Last Updated:** 2026-10-22  

---

## 1. Truthful Status Classification

| Capability | Operational State | Verification Basis | Boundary / Limitation |
|---|---|---|---|
| **Autonomous Engineering Pipeline** | `LIVE LOCAL` | Full 12-stage engine in `src/lib/autonomous-engineering/` | Operates on local fixture repositories (`services/nightshift-sde/fixtures/demo-repos/`). |
| **Real Test Execution** | `LIVE LOCAL` | Subprocess child runner | Discovers and executes local unit tests via Python standard library. |
| **NVIDIA NIM Acceleration** | `LIVE / ACCELERATED` | `src/lib/nvidia-nim.ts` | Uses live NVIDIA NIM if `NVIDIA_API_KEY` is present; otherwise falls back to deterministic TensorRT-LLM FP8 simulation (154 tok/s, 14.8ms). |
| **Nebius Token Factory** | `CONFIGURABLE` | Config in `.env.example` | Adapter supports `https://api.studio.nebius.ai/v1`. Marked `UNCONFIGURED` unless `NEBIUS_API_KEY` is provided. |
| **Remote GitHub PR Creation** | `UNCONFIGURED` | Delivery Agent Adapter | Without `GITHUB_TOKEN`, status is explicitly reported as `LOCAL_PATCH_ONLY / PR_NOT_CREATED_UNCONFIGURED`. No fake PRs are emitted. |
| **UNWIND Governance Authority** | `LIVE LOCAL` | Integer warrant ledger | Pure integer arithmetic (`1,450 bp`). Live external wire adapter remains unconfigured to fail closed. |
| **Cloud Infrastructure (AWS SNS/SQS)** | `UNCONFIGURED` | Adapters only | Zero AWS or Meta WhatsApp cloud resources deployed or billed. |
