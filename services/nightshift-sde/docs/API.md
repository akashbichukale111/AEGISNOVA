# API contract (generated from the route table)

All endpoints are JSON. Auth: `Authorization: Bearer <token>` (except `/api/health` and the HMAC-verified `/api/webhooks/github`). Roles: viewer < operator / approver < admin (explicit capability sets, see below).
Errors: `{"error": {"code", "message", "details", "correlation_id"}}`. Every response carries `X-Correlation-ID` (client-supplied ids are echoed only if well-formed). Bodies are capped (default 256 KiB), `Content-Type: application/json` required, chunked bodies refused, per-actor rate limits apply (429 + `Retry-After`).
Triggering supports an `Idempotency-Key` header (8–80 chars); a repeated key returns the original job with `created: false`.

| Method | Path | Auth | Handler |
|---|---|---|---|
| GET | `/api/health` | none/HMAC | `health` |
| GET | `/api/me` | bearer | `me` |
| GET | `/api/overview` | bearer | `overview` |
| GET | `/api/fleet` | bearer | `fleet` |
| GET | `/api/repos` | bearer | `repos` |
| POST | `/api/repos` | bearer | `repo_create` |
| GET | `/api/repos/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `repo_get` |
| PATCH | `/api/repos/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `repo_patch` |
| DELETE | `/api/repos/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `repo_delete` |
| POST | `/api/repos/(?P<id>[A-Za-z0-9_.:-]{1,80})/trigger` | bearer | `repo_trigger` |
| POST | `/api/repos/(?P<id>[A-Za-z0-9_.:-]{1,80})/check` | bearer | `repo_check` |
| GET | `/api/schedules` | bearer | `sched_list` |
| POST | `/api/schedules/validate` | bearer | `sched_validate` |
| POST | `/api/schedules` | bearer | `sched_create` |
| GET | `/api/schedules/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `sched_get` |
| PATCH | `/api/schedules/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `sched_patch` |
| DELETE | `/api/schedules/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `sched_delete` |
| POST | `/api/schedules/(?P<id>[A-Za-z0-9_.:-]{1,80})/(?P<action>[A-Za-z0-9_.:-]{1,80})` | bearer | `sched_action` |
| POST | `/api/scheduler/tick` | bearer | `scheduler_tick` |
| POST | `/api/watchdog/tick` | bearer | `watchdog_tick` |
| GET | `/api/jobs` | bearer | `jobs` |
| GET | `/api/jobs/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `job_get` |
| POST | `/api/jobs/(?P<id>[A-Za-z0-9_.:-]{1,80})/(?P<action>[A-Za-z0-9_.:-]{1,80})` | bearer | `job_action` |
| GET | `/api/jobs/(?P<id>[A-Za-z0-9_.:-]{1,80})/artifacts/(?P<aid>[A-Za-z0-9_.:-]{1,80})` | bearer | `artifact` |
| POST | `/api/approvals/(?P<id>[A-Za-z0-9_.:-]{1,80})/(?P<action>[A-Za-z0-9_.:-]{1,80})` | bearer | `approval_action` |
| GET | `/api/findings` | bearer | `findings` |
| GET | `/api/findings/(?P<id>[A-Za-z0-9_.:-]{1,80})` | bearer | `finding` |
| GET | `/api/recovery` | bearer | `recovery` |
| GET | `/api/audit` | bearer | `audit` |
| GET | `/api/audit/extras` | bearer | `audit_extras` |
| GET | `/api/settings` | bearer | `settings` |
| POST | `/api/providers/(?P<id>[A-Za-z0-9_.:-]{1,80})/check` | bearer | `provider_check` |
| GET | `/api/metrics` | bearer | `metrics` |
| POST | `/api/webhooks/github` | none/HMAC | `webhook` |

## Permissions

| Permission | Roles |
|---|---|
| read | viewer, operator, approver, admin |
| operate (trigger, pause/resume/cancel/retry/replay, schedules) | operator, admin |
| approve (approve/reject/revoke) | approver, admin |
| authorize_repair (request write-capable work) | approver, admin |
| admin (repositories, ticks) | admin |

Triggering write-capable work needs BOTH `operate` and `authorize_repair` (in practice: `admin`). The requester of a repair can never approve it (separation of duties, on by default).

## Job actions
`POST /api/jobs/{id}/{pause|resume|cancel|retry|replay}` — validity is decided server-side from the state machine; `GET /api/jobs/{id}` returns an `actions` list with `enabled` and a human `reason`, which the UI renders verbatim.

## Schedule body (create/validate)
`name, purpose, repo_id, kind (one_time|recurring), timezone (IANA), recurrence {type: interval|daily|weekly, every_minutes|at|days}, run_at_local (one_time), allow_repair, concurrency_policy (forbid|allow), misfire_policy (skip|run_once), misfire_grace_seconds, max_duration_seconds, retry_policy {max_attempts, base_seconds, max_seconds, max_elapsed_seconds}`. `POST /api/schedules/validate` is a dry run that returns a human-readable recurrence and the next runs.
