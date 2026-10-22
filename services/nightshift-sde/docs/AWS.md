# AWS mapping (design only — nothing here is built, deployed, or tested)

Local mode needs no AWS. Targets for a later phase, each replacing one local component behind the same interfaces:

| Local component | AWS target | Notes |
|---|---|---|
| `Scheduler.tick` | EventBridge Scheduler → API `POST /api/webhooks`-style trigger | keep `schedule_runs` UNIQUE + idempotency key as the dedupe layer |
| `jobs` table + worker | SQS + DLQ, workers on ECS/CodeBuild | lease/fence logic stays in the DB or moves to DynamoDB conditional writes |
| approval wait | Step Functions task-token callback | token stored server-side only; **never** placed in SNS/email/SMS |
| notifications | SNS | notifications are not credentials |
| artifacts | S3 (+ SSE-KMS) | store sha256 in the DB |
| secrets | Secrets Manager | no secrets in env files in deployment |
| metrics/alarms | CloudWatch | map `/api/metrics` counters |
| sandbox | CodeBuild / Firecracker-class isolation | current sandbox has NO filesystem confinement |

Required IAM, resource creation and cleanup steps must be written when this is actually built. Do not create cloud resources without explicit authorisation.
