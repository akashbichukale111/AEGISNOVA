-- NightShift SDE schema v1. Timestamps are fixed-width UTC ISO strings (lexicographic == chronological).
-- JSON columns hold canonical JSON text.

CREATE TABLE repositories (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  rel_path TEXT NOT NULL,                 -- path RELATIVE to NIGHTSHIFT_REPO_ROOT (never an arbitrary client path)
  default_branch TEXT NOT NULL DEFAULT 'main',
  policy_name TEXT NOT NULL DEFAULT 'default',
  test_command_key TEXT NOT NULL DEFAULT 'none',   -- key into the allowlisted command catalogue
  max_concurrent_jobs INTEGER NOT NULL DEFAULT 1,
  allow_repair INTEGER NOT NULL DEFAULT 0,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT
);

CREATE TABLE repo_snapshots (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repositories(id),
  job_id TEXT,
  tree_hash TEXT NOT NULL,
  commit_sha TEXT,
  file_count INTEGER NOT NULL,
  taken_at TEXT NOT NULL
);
CREATE INDEX idx_snapshots_repo ON repo_snapshots(repo_id, taken_at);

CREATE TABLE policies (
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  body TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (name, version)
);

CREATE TABLE schedules (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT '',
  repo_id TEXT NOT NULL REFERENCES repositories(id),
  kind TEXT NOT NULL CHECK (kind IN ('one_time','recurring')),
  timezone TEXT NOT NULL,
  recurrence TEXT,                         -- JSON for recurring
  run_at TEXT,                             -- UTC instant for one_time
  anchor_at TEXT NOT NULL,                 -- anchor for interval recurrences
  status TEXT NOT NULL CHECK (status IN ('active','paused','disabled','completed','deleted')),
  policy_name TEXT NOT NULL DEFAULT 'default',
  allow_repair INTEGER NOT NULL DEFAULT 0,
  concurrency_policy TEXT NOT NULL DEFAULT 'forbid' CHECK (concurrency_policy IN ('forbid','allow')),
  misfire_policy TEXT NOT NULL DEFAULT 'skip' CHECK (misfire_policy IN ('skip','run_once')),
  misfire_grace_seconds INTEGER NOT NULL DEFAULT 300,
  max_duration_seconds INTEGER NOT NULL DEFAULT 3600,
  retry_policy TEXT NOT NULL,              -- JSON
  next_run_at TEXT,
  last_run_at TEXT,
  last_status TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);
CREATE INDEX idx_schedules_due ON schedules(status, next_run_at);

CREATE TABLE schedule_runs (
  id TEXT PRIMARY KEY,
  schedule_id TEXT NOT NULL REFERENCES schedules(id),
  scheduled_for TEXT NOT NULL,
  fired_at TEXT NOT NULL,
  status TEXT NOT NULL,                    -- fired | catchup_fired | missed_skipped | skipped_concurrency | error
  job_id TEXT,
  lateness_seconds REAL NOT NULL DEFAULT 0,
  missed_count INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  UNIQUE (schedule_id, scheduled_for)      -- duplicate scheduled execution is impossible
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  repo_id TEXT NOT NULL REFERENCES repositories(id),
  schedule_id TEXT REFERENCES schedules(id),
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('schedule','manual','webhook','replay')),
  trigger_event_id TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  correlation_id TEXT NOT NULL,
  workflow_version TEXT NOT NULL,
  state TEXT NOT NULL,
  outcome TEXT,                            -- investigation_only | no_findings | repair_verified | repair_blocked | ...
  priority INTEGER NOT NULL DEFAULT 50,
  allow_repair INTEGER NOT NULL DEFAULT 0, -- write-capable authorisation recorded at trigger time
  requested_by TEXT NOT NULL,
  policy_name TEXT NOT NULL DEFAULT 'default',
  policy_version INTEGER,
  retry_policy TEXT NOT NULL,
  stage_timeout_seconds INTEGER NOT NULL,
  deadline_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  queued_at TEXT,
  available_at TEXT,
  retry_at TEXT,
  first_started_at TEXT,
  finished_at TEXT,
  attempt INTEGER NOT NULL DEFAULT 0,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  replan_count INTEGER NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_expires_at TEXT,
  fence INTEGER NOT NULL DEFAULT 0,
  last_heartbeat_at TEXT,
  last_progress_at TEXT,
  last_progress_note TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  pause_requested INTEGER NOT NULL DEFAULT 0,
  replay_of TEXT REFERENCES jobs(id),
  base_tree TEXT,
  base_commit TEXT,
  result TEXT,                             -- JSON
  error TEXT                               -- JSON (structured error + recovery recommendation)
);
CREATE INDEX idx_jobs_state ON jobs(state);
CREATE INDEX idx_jobs_repo_state ON jobs(repo_id, state);
CREATE INDEX idx_jobs_schedule ON jobs(schedule_id);
CREATE INDEX idx_jobs_queue ON jobs(state, available_at, priority);
CREATE INDEX idx_jobs_lease ON jobs(lease_expires_at);

CREATE TABLE job_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  from_state TEXT,
  to_state TEXT NOT NULL,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  source TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  detail TEXT,
  attempt INTEGER NOT NULL,
  fence INTEGER NOT NULL,
  correlation_id TEXT NOT NULL
);
CREATE INDEX idx_transitions_job ON job_transitions(job_id, id);

CREATE TABLE job_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  attempt_no INTEGER NOT NULL,
  worker_id TEXT NOT NULL,
  fence INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  end_state TEXT,
  error TEXT,
  UNIQUE (job_id, attempt_no)
);

CREATE TABLE checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  seq INTEGER NOT NULL,
  attempt INTEGER NOT NULL,
  stage TEXT NOT NULL,
  data TEXT NOT NULL,
  checksum TEXT NOT NULL,
  base_tree TEXT,
  base_commit TEXT,
  policy_name TEXT,
  policy_version INTEGER,
  workflow_version TEXT NOT NULL,
  evidence_retrieved_at TEXT,
  valid INTEGER NOT NULL DEFAULT 1,
  invalidated_reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (job_id, seq)
);

CREATE TABLE findings (
  id TEXT PRIMARY KEY,                     -- stable: hash(repo, ecosystem, package, sorted advisory ids)
  repo_id TEXT NOT NULL REFERENCES repositories(id),
  last_job_id TEXT,
  package TEXT NOT NULL,
  ecosystem TEXT NOT NULL,
  installed_version TEXT,
  relationship TEXT NOT NULL,              -- direct | transitive | unknown
  manifest_paths TEXT NOT NULL,            -- JSON list
  advisory_ids TEXT NOT NULL,              -- JSON list
  affected_ranges TEXT NOT NULL,           -- JSON
  fixed_candidates TEXT NOT NULL,          -- JSON list
  selected_fix TEXT,
  severity TEXT NOT NULL,
  risk_score INTEGER,
  risk_tier TEXT,
  reason_codes TEXT NOT NULL,              -- JSON list
  evidence_status TEXT NOT NULL,           -- confirmed | stale | conflicting
  confidence TEXT NOT NULL,
  limitations TEXT NOT NULL,               -- JSON list
  recommended_action TEXT NOT NULL,
  requires_approval INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'open',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX idx_findings_repo ON findings(repo_id, status);

CREATE TABLE finding_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  finding_id TEXT NOT NULL REFERENCES findings(id),
  job_id TEXT NOT NULL,
  repo_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  installed_version TEXT,
  severity TEXT NOT NULL,
  risk_score INTEGER,
  evidence_status TEXT NOT NULL,
  UNIQUE (finding_id, job_id)
);

CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  finding_id TEXT,
  repo_id TEXT NOT NULL,
  source TEXT NOT NULL,                    -- provider name
  source_mode TEXT NOT NULL,               -- live | local-file | fixture | stub
  advisory_id TEXT NOT NULL,
  package TEXT NOT NULL,
  ecosystem TEXT NOT NULL,
  url TEXT,
  retrieved_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  summary TEXT NOT NULL,                   -- JSON; untrusted text is sanitised and length-capped
  flags TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_evidence_job ON evidence(job_id);
CREATE INDEX idx_evidence_finding ON evidence(finding_id);

CREATE TABLE risk_assessments (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  policy_name TEXT NOT NULL,
  policy_version INTEGER NOT NULL,
  score INTEGER NOT NULL,
  tier TEXT NOT NULL,
  reason_codes TEXT NOT NULL,
  repair_decision TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_risk_job ON risk_assessments(job_id);

CREATE TABLE approvals (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  repo_id TEXT NOT NULL,
  provider TEXT NOT NULL,                  -- 'dev-stub' here; 'unwind' via adapter later
  status TEXT NOT NULL CHECK (status IN ('pending','approved','rejected','revoked','expired','superseded')),
  scope TEXT NOT NULL,                     -- JSON
  scope_hash TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  decided_by TEXT,
  decided_at TEXT,
  decision_note TEXT,
  revoked_by TEXT,
  revoked_at TEXT,
  revoke_reason TEXT
);
CREATE INDEX idx_approvals_job ON approvals(job_id);
CREATE INDEX idx_approvals_status ON approvals(status, expires_at);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  kind TEXT NOT NULL,                      -- patch | test_log | verifier_report | repair_proof | inspection_report
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (job_id, kind, name)
);

CREATE TABLE recovery_actions (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  schedule_id TEXT,
  kind TEXT NOT NULL,
  actor TEXT NOT NULL,
  source TEXT NOT NULL,                    -- operator | watchdog | system
  result TEXT NOT NULL,
  detail TEXT,
  correlation_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_recovery_created ON recovery_actions(created_at);

CREATE TABLE alerts (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  severity TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  repo_id TEXT,
  condition TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  detected_at TEXT NOT NULL,
  last_progress TEXT,
  recommended_action TEXT NOT NULL,
  auto_recovery_attempted INTEGER NOT NULL DEFAULT 0,
  recovery_result TEXT,
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  resolved_at TEXT,
  dedupe_key TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_alerts_open_dedupe ON alerts(dedupe_key) WHERE status = 'open';
CREATE INDEX idx_alerts_status ON alerts(status, detected_at);

CREATE TABLE provider_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  operation TEXT NOT NULL,
  ok INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL,
  error_code TEXT,
  at TEXT NOT NULL,
  correlation_id TEXT
);
CREATE INDEX idx_provider_calls ON provider_calls(provider, at);

CREATE TABLE provider_health (
  provider TEXT PRIMARY KEY,
  mode TEXT NOT NULL,                      -- live | local-file | stub | unconfigured | disabled
  status TEXT NOT NULL,                    -- ok | degraded | down | unverified | unconfigured
  last_check_at TEXT,
  last_success_at TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_error_code TEXT,
  detail TEXT
);

CREATE TABLE notifications (
  id TEXT PRIMARY KEY,
  job_id TEXT,
  event_type TEXT NOT NULL,
  channel TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL,
  status TEXT NOT NULL,                    -- pending | recorded_local | delivered | failed
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_notifications_status ON notifications(status);

CREATE TABLE webhook_deliveries (
  source TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  repo_id TEXT,
  received_at TEXT NOT NULL,
  job_id TEXT,
  outcome TEXT NOT NULL,
  PRIMARY KEY (source, delivery_id)
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  type TEXT NOT NULL,
  actor TEXT NOT NULL,
  job_id TEXT,
  repo_id TEXT,
  schedule_id TEXT,
  data TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
CREATE INDEX idx_events_job ON events(job_id, id);
CREATE INDEX idx_events_repo ON events(repo_id, id);
CREATE INDEX idx_events_type ON events(type, id);
CREATE INDEX idx_events_ts ON events(ts);

CREATE TABLE counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE workers (
  id TEXT PRIMARY KEY,
  pid INTEGER,
  host TEXT,
  started_at TEXT NOT NULL,
  last_heartbeat_at TEXT NOT NULL,
  current_job_id TEXT,
  status TEXT NOT NULL,
  version TEXT NOT NULL
);

-- Append-only enforcement (DB-level). This is NOT cryptographic immutability on its own;
-- events additionally carry a hash chain that verify_chain() can check.
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER transitions_no_update BEFORE UPDATE ON job_transitions BEGIN SELECT RAISE(ABORT, 'job_transitions are append-only'); END;
CREATE TRIGGER transitions_no_delete BEFORE DELETE ON job_transitions BEGIN SELECT RAISE(ABORT, 'job_transitions are append-only'); END;
