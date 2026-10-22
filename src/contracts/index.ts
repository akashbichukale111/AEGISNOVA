/**
 * AEGISNOVA Canonical Schema Contracts (v1.0.0)
 * ============================================
 * Unified versioned data contracts across DevGuard AI, DevGuard Enterprise,
 * UNWIND Governance Core, and the five future feature modules.
 */

export const SCHEMA_VERSION = "1.0.0";

export type HealthStatus = "CONNECTED" | "NOT_CONNECTED" | "PLANNED" | "DEMO" | "ERROR" | "LOCAL" | "SIMULATED" | "UNCONFIGURED";

export type SeverityLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFORMATIONAL";

export type ApprovalState = "PENDING" | "APPROVED" | "REJECTED" | "REVOKED" | "EXPIRED";

export type WorkflowStatus = "QUEUED" | "RUNNING" | "PAUSED_APPROVAL" | "COMPLETED" | "FAILED" | "RETRYING" | "CANCELLED";

/**
 * 1. Repository
 */
export interface Repository {
  schemaVersion: "1.0.0";
  id: string; // e.g. "repo-aegis-core"
  name: string; // "aegisnova/core"
  cloneUrl: string;
  defaultBranch: string;
  isMonitored: boolean;
  scanPolicy: "STRICT" | "STANDARD" | "AUDIT_ONLY";
  lastScannedAt?: string; // ISO 8601
  openFindingsCount: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
}

/**
 * 2. ScanJob
 */
export interface ScanJob {
  schemaVersion: "1.0.0";
  id: string; // "scan-2026-001"
  repositoryId: string;
  correlationId: string;
  commitSha: string;
  initiatedBy: string; // "system" | "user:sec-eng-01"
  status: "QUEUED" | "SCANNING" | "ANALYZING" | "COMPLETED" | "FAILED";
  startedAt: string;
  completedAt?: string;
  findingsCount: number;
  isDemo: boolean;
}

/**
 * 3. Finding
 */
export interface Finding {
  schemaVersion: "1.0.0";
  id: string; // "find-sec-941"
  scanJobId: string;
  repositoryId: string;
  ruleId: string; // e.g. "CWE-89" | "HARDCODED_SECRET" | "PROMPT_INJECTION"
  title: string;
  description: string;
  severity: SeverityLevel;
  filePath: string;
  lineNumber: number;
  codeSnippet: string;
  status: "OPEN" | "TRIAGED" | "PATCH_PROPOSED" | "RESOLVED" | "IGNORED";
  isDemo: boolean;
  createdAt: string;
}

/**
 * 4. PatchProposal
 */
export interface PatchProposal {
  schemaVersion: "1.0.0";
  id: string; // "patch-772"
  findingId: string;
  proposedBy: "devguard-ai-fixer" | "human" | "nightshift-sde";
  diff: string; // unified diff string
  explanation: string;
  confidenceScore: number; // 0.0 - 1.0
  governanceRequired: boolean;
  approvalRequestId?: string;
  applied: boolean;
  appliedAt?: string;
}

/**
 * 5. ValidationResult
 */
export interface ValidationResult {
  schemaVersion: "1.0.0";
  id: string; // "val-882"
  patchProposalId: string;
  syntaxValid: boolean;
  testSuitePassed: boolean;
  regressionDetected: boolean;
  independentProofId?: string;
  verifiedAt: string;
  summary: string;
}

/**
 * 6. WorkflowRun
 */
export interface WorkflowRun {
  schemaVersion: "1.0.0";
  id: string; // "wf-501"
  title: string;
  module: "NightShift SDE" | "DevGuard Pipeline" | "Autonomous Ops";
  status: WorkflowStatus;
  currentStep: string;
  totalSteps: number;
  completedSteps: number;
  correlationId: string;
  startedAt: string;
  updatedAt: string;
  isDemo: boolean;
  // Extended fields from Autonomous Operations backend
  workflowType?: string;
  payload?: Record<string, unknown>;
  attempts?: number;
  requiresApproval?: boolean;
  approvalId?: string;
  lastError?: string;
  cancelReason?: string;
}

/**
 * 6.1 WorkflowTimelineEvent
 */
export interface WorkflowTimelineEvent {
  schemaVersion: "1.0.0";
  id: string;
  runId: string;
  type: string;
  fromState?: string;
  toState?: string;
  step?: string;
  actor: string;
  ts: string;
  correlationId?: string;
  detail?: Record<string, unknown>;
}

/**
 * 7. ApprovalRequest (UNWIND Governance Core)
 */
export interface ApprovalRequest {
  schemaVersion: "1.0.0";
  id: string; // "appr-094"
  actionType: "APPLY_SECURITY_PATCH" | "RETRY_JOB" | "INFRA_MUTATION" | "SECRET_ROTATION" | "SAMPLE_GOVERNED_ACTION";
  actionPayload: Record<string, unknown>;
  severity: SeverityLevel;
  requiredScope: string; // e.g. "scope:repo:write"
  warrantDebitBp: number; // UNWIND warrant basis points
  expiresAt: string;
  createdAt: string;
  state: ApprovalState;
  requestedBy: string;
  // Extensions
  devOnly?: boolean;
  decisionRef?: string;
  blockedReason?: string;
  runId?: string;
}

/**
 * 8. ApprovalDecision (UNWIND Governance Core)
 */
export interface ApprovalDecision {
  schemaVersion: "1.0.0";
  approvalRequestId: string;
  decision: "APPROVED" | "REJECTED" | "REVOKED";
  decidedBy: string; // e.g. "human:sre-lead@aegisnova.io"
  decidedAt: string;
  decisionReason: string;
  decisionLineageHash: string; // Deterministic sha256 of outcome
  warrantBalanceRemainingBp: number;
  isDevDecision?: boolean;
}

/**
 * 9. EvidenceReference (Future Evidence Intelligence)
 */
export interface EvidenceReference {
  schemaVersion: "1.0.0";
  id: string; // "ev-301"
  sourceType: "GHSA" | "OSV" | "NVD" | "INTERNAL_CORPUS" | "TAVILY";
  sourceUri: string;
  confidenceScore: number;
  freshnessTimestamp: string;
  isConflict: boolean;
  citationText: string;
}

/**
 * 10. ImpactAnalysis (Future Causal Impact Intelligence)
 */
export interface ImpactAnalysis {
  schemaVersion: "1.0.0";
  id: string; // "imp-401"
  findingOrIncidentId: string;
  blastRadiusScore: number; // 0 - 100
  affectedServices: string[];
  rootCauseHypotheses: Array<{
    hypothesis: string;
    probability: number;
  }>;
  uncertaintyBand: "LOW" | "MODERATE" | "HIGH";
  isCausalVerified: boolean;
}

/**
 * 11. RepairProof (Future Independent Repair Assurance)
 */
export interface RepairProof {
  schemaVersion: "1.0.0";
  id: string; // "proof-501"
  patchId: string;
  patchBreakerSurvived: boolean;
  warrantyStatus: "WARRANTED" | "PROVISIONAL" | "REFUSED";
  residualRiskScore: number; // 0 - 100
  attestationHash: string;
}

/**
 * 12. NotificationStatus (Autonomous Ops & Notifications)
 */
export interface NotificationStatus {
  schemaVersion: "1.0.0";
  channel: "SNS_EMAIL" | "SNS_SMS" | "WHATSAPP_OFFICIAL" | "SLACK_WEBHOOK" | "LOCAL_SINK";
  configured: boolean;
  healthy: boolean;
  lastDeliveredAt?: string;
  queuedCount: number;
  // Extended fields
  id?: string;
  runId?: string;
  mode?: "LOCAL" | "SIMULATED" | "REAL";
  destinationMasked?: string;
  template?: string;
  status?: "ACCEPTED" | "DELIVERED" | "FAILED" | "SUPPRESSED" | "DEAD_LETTERED" | "UNKNOWN";
  attempts?: number;
  provider?: string;
  providerMessageId?: string;
  deliveryVerified?: boolean;
  lastError?: string;
  errorClass?: string;
}

/**
 * 12.1 DeadLetterItem
 */
export interface DeadLetterItem {
  schemaVersion: "1.0.0";
  id: string;
  kind: string;
  entityId: string;
  payloadHash: string;
  errorClass: string;
  error: string;
  status: "DEAD_LETTERED" | "REDRIVEN";
  redriveCount: number;
  createdAt: string;
  correlationId?: string;
}

/**
 * 12.2 OperationalAlarm
 */
export interface OperationalAlarm {
  schemaVersion: "1.0.0";
  alarmName: string;
  state: "OK" | "ALARM" | "COOLDOWN";
  lastValue?: number;
  threshold: number;
  since: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  explanation: string;
  runbook: string;
}

/**
 * 13. AuditEvent
 */
export interface AuditEvent {
  schemaVersion: "1.0.0";
  id: string; // "audit-102"
  timestamp: string;
  actor: string;
  action: string;
  targetResource: string;
  correlationId: string;
  outcome: "SUCCESS" | "FAILURE" | "INTERCEPTED";
  warrantBurnedBp?: number;
  metadata?: Record<string, unknown>;
}

/**
 * 14. IntegrationHealth
 */
export interface IntegrationHealth {
  schemaVersion: "1.0.0";
  moduleKey: string; // "devguard_ai" | "unwind_governance" | "feature_05_ops" etc.
  displayName: string;
  status: HealthStatus;
  version: string;
  lastHeartbeat?: string;
  description: string;
  details: string;
  envVarsRequired?: string[];
  blockerReason?: string;
}

/**
 * =========================================================================
 * AUTONOMOUS ENGINEERING & PROOF-CARRYING PULL REQUEST (PCPR) CONTRACTS
 * =========================================================================
 */

export type AutonomyMode = "PLAN_ONLY" | "LOCAL_SANDBOX" | "PATCH_AND_VERIFY" | "CREATE_PR";

export type AgentRunStatus =
  | "INITIALIZING"
  | "RUNNING"
  | "AWAITING_APPROVAL"
  | "READY_FOR_REVIEW"
  | "BLOCKED"
  | "FAILED"
  | "CANCELLED";

export type VerifierVerdict = "PASS" | "PASS_WITH_RESIDUAL_RISK" | "NEEDS_CHANGES" | "BLOCKED";

export interface RepositoryTarget {
  id: string; // "demo/payments-service"
  name: string;
  path: string;
  defaultBranch: string;
  testCommand: string;
  buildManifest: string;
  isMonitored: boolean;
}

export interface IssueTask {
  id: string; // "TASK-SEC-01"
  title: string;
  description: string;
  targetRepoId: string;
  acceptanceCriteria: string[];
  severity: SeverityLevel;
  autonomyMode: AutonomyMode;
  allowHighRiskWrites: boolean;
}

export interface CommandExecution {
  command: string;
  args: string[];
  cwd: string;
  exitCode: number;
  durationMs: number;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  timestamp: string;
}

export interface TestResult {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  durationSeconds: number;
  commandExecution: CommandExecution;
  failures: Array<{ testName: string; trace: string }>;
}

export interface ChangedFile {
  path: string;
  originalHash: string;
  patchedHash: string;
  additions: number;
  deletions: number;
  diff: string;
}

export interface PlanStep {
  id: string;
  title: string;
  agentRole: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";
  checkpointRef?: string;
  outputSummary?: string;
}

export interface Checkpoint {
  id: string;
  runId: string;
  stepNumber: number;
  timestamp: string;
  treeHash: string;
  stateSnapshot: Record<string, unknown>;
}

export interface SecurityFinding {
  ruleId: string;
  title: string;
  severity: SeverityLevel;
  filePath: string;
  lineNumber: number;
  remediated: boolean;
  confidence: number;
}

export interface EvidenceItem {
  source: "OSV" | "GHSA" | "Tavily" | "NVD" | "INTERNAL";
  referenceId: string;
  summary: string;
  url?: string;
  retrievedAt: string;
  isFresh: boolean;
}

export interface ImpactHypothesis {
  targetComponent: string;
  directDependents: string[];
  blastRadiusPercent: number;
  confidenceScore: number;
  counterfactualOutcome: string;
}

export interface VerifierFinding {
  category: "CORRECTNESS" | "SECURITY" | "REGRESSION" | "SCOPE" | "SECRET_LEAK";
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  filePath: string;
  lineNumber?: number;
  observation: string;
  blocking: boolean;
}

export interface GovernanceDecision {
  approvalId: string;
  decidedBy: string;
  decision: "APPROVED" | "REJECTED" | "REVOKED";
  timestamp: string;
  warrantDebitedBp: number;
  warrantBalanceRemainingBp: number;
  reason: string;
  lineageHash: string;
}

export interface ResidualRisk {
  category: string;
  riskDescription: string;
  mitigation: string;
  operatorAccepted: boolean;
}

export interface PullRequestResult {
  status: "PR_CREATED" | "PR_NOT_CREATED_UNCONFIGURED" | "LOCAL_PATCH_ONLY" | "BLOCKED";
  branchName?: string;
  commitHash?: string;
  prUrl?: string;
  prNumber?: number;
  explanation: string;
}

/**
 * =========================================================================
 * GITHUB CONNECTION & REPOSITORY INTELLIGENCE AUDIT CONTRACTS
 * =========================================================================
 */

export interface GitHubConnection {
  status: "CONNECTED" | "UNCONFIGURED" | "RATE_LIMITED" | "INVALID_TOKEN";
  username?: string;
  avatarUrl?: string;
  scopes?: string[];
  tokenConfigured: boolean;
  rateLimitRemaining?: number;
  rateLimitReset?: string;
}

export interface RepoAuditFinding {
  id: string;
  ruleId: string;
  title: string;
  description: string;
  severity: SeverityLevel;
  confidence: number;
  filePath: string;
  lineNumber?: number;
  codeSnippet?: string;
  category: "SECURITY" | "BUG" | "DEPENDENCY" | "TESTING" | "MAINTAINABILITY";
  isHypothesis: boolean;
  recommendedFix: string;
  regressionTestSuggestion?: string;
}

export interface RepoArchitectureMap {
  repoId: string;
  repoName: string;
  defaultBranch: string;
  commitSha: string;
  languages: Record<string, number>; // e.g. { Python: 85, Shell: 15 }
  entryPoints: string[];
  testRunnersDiscovered: string[];
  manifestsFound: string[];
  dependencies: Array<{ name: string; versionSpec: string; ecosystem: string }>;
  totalFilesScanned: number;
  coveragePercentage: number;
}

export interface RepoAuditReport {
  schemaVersion: "1.0.0";
  reportId: string;
  repoTarget: RepositoryTarget;
  commitSha: string;
  architectureMap: RepoArchitectureMap;
  findings: RepoAuditFinding[];
  summary: {
    criticalCount: number;
    highCount: number;
    mediumCount: number;
    lowCount: number;
    hypothesesCount: number;
  };
  timestamp: string;
}

export interface EvidenceManifest {
  schemaVersion: "1.0.0";
  manifestHash: string; // SHA-256 hash of entire proof package
  runId: string;
  repoId: string;
  issueId: string;
  timestamp: string;
  modelUsed: string;
  diffHash: string;
  changedFiles: ChangedFile[];
  commandExecutions: CommandExecution[];
  testResults: TestResult;
  securityFindings: SecurityFinding[];
  evidenceSources: EvidenceItem[];
  impactAnalysis: ImpactHypothesis;
  verifierVerdict: VerifierVerdict;
  verifierFindings: VerifierFinding[];
  governanceDecision?: GovernanceDecision;
  pullRequestResult: PullRequestResult;
  residualRisks: ResidualRisk[];
  unwindWarrantDebitBp: number;
}

export interface AgentEvent {
  id: string;
  runId: string;
  timestamp: string;
  agentRole:
    | "Repository Intelligence"
    | "Issue Analyst"
    | "Planner / Orchestrator"
    | "Autonomous Coding Agent"
    | "Test Engineer"
    | "DevGuard Security Analyst"
    | "Evidence Researcher"
    | "Causal Impact Agent"
    | "Independent Verifier"
    | "Repair Assurance"
    | "UNWIND Governance Core"
    | "GitHub Delivery Agent";
  action: string;
  status: "INFO" | "SUCCESS" | "WARNING" | "ERROR";
  details: string;
  evidenceRef?: string;
}

export interface AgentRun {
  id: string; // e.g. "RUN-ENG-2026-001"
  repoTarget: RepositoryTarget;
  issueTask: IssueTask;
  status: AgentRunStatus;
  currentStepIndex: number;
  plan: PlanStep[];
  events: AgentEvent[];
  changedFiles: ChangedFile[];
  manifest?: EvidenceManifest;
  createdAt: string;
  updatedAt: string;
  startedAt?: string;
  completedAt?: string;
}

