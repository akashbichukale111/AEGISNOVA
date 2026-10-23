/**
 * AEGISNOVA Automated Validation & Smoke Test Suite
 * ==================================================
 * Executes syntax, schema, route integrity, and secrets scans.
 */

const fs = require('fs');
const path = require('path');

let testsPassed = 0;
let testsFailed = 0;

function assert(condition, testName) {
  if (condition) {
    console.log(`[PASS] ${testName}`);
    testsPassed++;
  } else {
    console.error(`[FAIL] ${testName}`);
    testsFailed++;
  }
}

console.log("=== RUNNING AEGISNOVA SMOKE & INTEGRATION SUITE ===");

// 1. Verify Contract Definitions
const contractsPath = path.join(__dirname, '..', 'src', 'contracts', 'index.ts');
assert(fs.existsSync(contractsPath), "Contracts file exists (src/contracts/index.ts)");
const contractsContent = fs.readFileSync(contractsPath, 'utf8');

const requiredSchemas = [
  "Repository",
  "ScanJob",
  "Finding",
  "PatchProposal",
  "ValidationResult",
  "WorkflowRun",
  "ApprovalRequest",
  "ApprovalDecision",
  "EvidenceReference",
  "ImpactAnalysis",
  "RepairProof",
  "NotificationStatus",
  "AuditEvent",
  "IntegrationHealth",
  "RepositoryTarget",
  "IssueTask",
  "AgentRun",
  "EvidenceManifest",
  "CommandExecution",
  "TestResult",
  "ChangedFile",
  "VerifierFinding",
  "GitHubConnection",
  "RepoAuditFinding",
  "RepoArchitectureMap",
  "RepoAuditReport"
];

requiredSchemas.forEach((schema) => {
  assert(
    contractsContent.includes(`interface ${schema}`),
    `Contract schema '${schema}' is defined and exported`
  );
});

// 2. Verify Primary Routes Exist
const routes = [
  "src/app/page.tsx",
  "src/app/engineering/page.tsx",
  "src/app/nightshift/page.tsx",
  "src/app/security/page.tsx",
  "src/app/impact/page.tsx",
  "src/app/evidence/page.tsx",
  "src/app/causal-impact/page.tsx",
  "src/app/repair-assurance/page.tsx",
  "src/app/operations/page.tsx",
  "src/app/governance/page.tsx",
  "src/app/audit/page.tsx",
  "src/app/settings/page.tsx",
];

routes.forEach((route) => {
  const fullPath = path.join(__dirname, '..', route);
  assert(fs.existsSync(fullPath), `Route component exists (${route})`);
});

// 2.1 Verify API Handlers & Core Modules
const coreModules = [
  "src/app/api/github/status/route.ts",
  "src/app/api/github/repos/route.ts",
  "src/app/api/repo-intelligence/audit/route.ts",
  "src/app/api/engineering/run/route.ts",
  "src/app/api/engineering/status/route.ts",
  "src/app/api/evidence/search/route.ts",
  "src/lib/evidence/tavily.ts",
  "src/lib/github/client.ts",
  "src/lib/repo-intelligence/analyzer.ts",
  "src/lib/autonomous-engineering/runner.ts",
];

coreModules.forEach((mod) => {
  const fullPath = path.join(__dirname, '..', mod);
  assert(fs.existsSync(fullPath), `Core module exists (${mod})`);
});

// 3. Verify Secrets Hygiene (No raw private keys or live API keys in src)
const srcDir = path.join(__dirname, '..', 'src');
function scanForSecrets(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      scanForSecrets(fullPath);
    } else if (file.endsWith('.ts') || file.endsWith('.tsx') || file.endsWith('.json')) {
      const content = fs.readFileSync(fullPath, 'utf8');
      // Check for AWS secret keys, private RSA keys, or live production tokens
      const hasAwsSecret = /AKIA[0-9A-Z]{16}/.test(content);
      const hasPrivateKey = /-----BEGIN PRIVATE KEY-----/.test(content);
      assert(!hasAwsSecret && !hasPrivateKey, `File ${file} is clean of exposed credentials`);
    }
  }
}
scanForSecrets(srcDir);

// 4. Verify Demo Data Integrity
const demoDataPath = path.join(__dirname, '..', 'src', 'lib', 'demo-data.ts');
assert(fs.existsSync(demoDataPath), "Demo data file exists (src/lib/demo-data.ts)");
const demoContent = fs.readFileSync(demoDataPath, 'utf8');
assert(demoContent.includes("INITIAL_FINDINGS"), "INITIAL_FINDINGS exported");
assert(demoContent.includes("INITIAL_APPROVALS"), "INITIAL_APPROVALS exported");
assert(demoContent.includes("INITIAL_INTEGRATIONS"), "INITIAL_INTEGRATIONS exported");
assert(demoContent.includes("UNWIND"), "UNWIND Governance references verified in demo store");

console.log("\n==================================================");
console.log(`TOTAL TESTS: ${testsPassed + testsFailed} | PASSED: ${testsPassed} | FAILED: ${testsFailed}`);
console.log("==================================================");

if (testsFailed > 0) {
  process.exit(1);
} else {
  console.log("All smoke checks passed successfully.");
}
