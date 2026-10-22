# API v1 (127.0.0.1 only, JSON, 1 MB body limit, errors `{"error":{"code","message"}}`)
GET /v1/health · GET /v1/repos · GET /v1/demo · POST /v1/runs {repo, base_sha, patch, claim{summary,tests_passed,files}, warrant?, demo_warrant?, warranty_days?}
GET /v1/runs/{id} | /breaker | /risk | /proof | /proof/report | /warrant · POST /v1/warrants/check {warrant, context{repo_id,base_sha,patch_hash,paths,action}}
GET|POST /v1/warranty/{id}[/check|/revalidate] (body: repo "@snapshot" or fixture name, triggers[]).
Codes: BAD_JSON, BAD_REQUEST, BAD_REPO, BAD_ID, NOT_FOUND, PAYLOAD_TOO_LARGE, INTERNAL; run-level error codes: MALFORMED, PATH_ABSOLUTE, PATH_TRAVERSAL, FORBIDDEN_PATH, PATCH_TOO_LARGE, BINARY_REJECTED, DOES_NOT_APPLY, BASE_MISMATCH.
`repo` is a fixture name under IRA_REPO_ROOT (no arbitrary host paths). No authentication: bind is loopback only; do not expose.
