# Security notes & threat model

| Threat | Mitigation in this build | Residual risk |
|---|---|---|
| Prompt injection via repo files / advisories / logs | No model is used; repository content is parsed as data only; `untrusted.py` sanitises it and flags instruction-like text for human visibility; decisions are deterministic | If a model is added later it must consume this content as data only |
| Malicious package scripts / arbitrary code | Repairs run only allowlisted commands (`COMMAND_LABELS`) in a temp workspace under an `unshare` network namespace, rlimits (CPU/mem/output/time), scrubbed env; fail closed if the sandbox is unavailable | **No filesystem confinement.** Run on a disposable host/container for untrusted code |
| Path traversal / symlinks / archive attacks | `repo.resolve_repo_path` confines to the repository root, rejects symlink escapes; patched files limited to approved paths | — |
| Secret exfiltration / log exposure | Central redactor on logs and every API response; tokens stored hashed in memory, dev tokens in a 0600 file under `data/` (excluded from the ZIP); UI never receives secrets | Redaction is pattern/registry based |
| Unauthorised writes | Role capabilities enforced server-side; write-capable runs need `operate`+`authorize_repair`, a scoped approval by a *different* principal, passing tests and verifier agreement | Dev-stub governance is not UNWIND |
| Stale approvals / TOCTOU | `READY_TO_EXECUTE` re-validates base tree/commit, policy version, evidence freshness and approval validity on every pass, including after resume | — |
| Duplicate / replayed webhooks | HMAC-SHA256 verification (constant time), delivery-id dedupe, idempotency keys | Secret management is the operator's job |
| Worker lease races | Lease + monotonically increasing fence token on every write; stale workers abort | SQLite single-node; multi-node needs a different store |
| DoS by repeated triggers | Per-actor rate limits, per-repo queue cap, concurrency limits, body size cap | Local thread-per-request server is not internet-hardened |
| SSRF | Only the configured OSV URL / notification webhook are contacted; nothing user-supplied is fetched | — |
| Cross-repository leakage | Repo-scoped queries and approvals; checkpoints carry repo identity | — |
| Notification spoofing | Notifications carry no approval credentials; approval only via authenticated API | Local channel is an outbox record, not delivery |
| XSS in console | DOM built with text nodes only (tested: no `innerHTML`), strict CSP (`script-src 'self'`, no inline) | — |
| Audit tampering | Hash-chained events with `verify-audit` | Tamper-*evident* only; not cryptographically immutable / externally anchored |

Bind address defaults to 127.0.0.1. There is no TLS: put it behind a TLS-terminating proxy if exposed.
