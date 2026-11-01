/**
 * AEGISNOVA Copilot & 3 AM Patrol Incident Fixtures
 * ==================================================
 * Realistic test fixtures simulating diverse production on-call events
 * across the Dual Autonomy Policy spectrum.
 */

import { NightShiftIncident, RecurrentIncidentMemory } from "@/contracts";

export const DEMO_INCIDENT_FIXTURES: NightShiftIncident[] = [
  {
    id: "inc-patrol-301",
    repoId: "demo/payments-service",
    repoUrl: "https://github.com/akashbichukale111/AEGISNOVA",
    title: "SQL Injection Vector in Payment Webhook Signature Validator",
    description: "Raw string interpolation detected in SQL statement execution during transaction verification.",
    severity: "CRITICAL",
    detectedAt: "2026-11-01T03:14:22Z",
    action: "WAITING_FOR_SDE_APPROVAL",
    requiresSdeApproval: true,
    sdeApproved: false,
    patchSummary: "Sanitized query parameters with parametrized query placeholders in db.execute()",
    testPassProof: "Deterministic exitCode 0 on 14/14 unit tests in sandbox harness.",
    evidenceRef: "Tavily AI: NIST CVE-2024-SQL-01 Advisory"
  },
  {
    id: "inc-patrol-302",
    repoId: "demo/auth-gateway",
    repoUrl: "https://github.com/akashbichukale111/AEGISNOVA",
    title: "Hardcoded Staging JWT Secret Key in Config Fallback",
    description: "Static JWT secret key detected in source code fallback branch.",
    severity: "HIGH",
    detectedAt: "2026-11-01T03:22:05Z",
    action: "WAITING_FOR_SDE_APPROVAL",
    requiresSdeApproval: true,
    sdeApproved: false,
    patchSummary: "Replaced hardcoded string with environment variable lookup and fatal startup assertion.",
    testPassProof: "Auth token validation suite passed without regression.",
    evidenceRef: "CWE-798: Use of Hard-coded Credentials"
  },
  {
    id: "inc-patrol-303",
    repoId: "demo/orders-worker",
    repoUrl: "https://github.com/akashbichukale111/AEGISNOVA",
    title: "Unpinned Dependency Drift in requirements.txt",
    description: "Dependency 'acme-httpkit' lacked pinned version tag, leading to build drift.",
    severity: "LOW",
    detectedAt: "2026-11-01T03:31:00Z",
    action: "AUTO_RESOLVED_NO_SDE_WAKEUP",
    requiresSdeApproval: false,
    sdeApproved: false,
    patchSummary: "Pinned version to acme-httpkit==1.2.0 based on last known stable build hash.",
    testPassProof: "Requirements check passed exitCode 0."
  },
  {
    id: "inc-patrol-304",
    repoId: "demo/inventory-api",
    repoUrl: "https://github.com/akashbichukale111/AEGISNOVA",
    title: "Database Connection Pool Timeout Spike",
    description: "Max connection pool exhausted under concurrent inventory release queries.",
    severity: "MEDIUM",
    detectedAt: "2026-11-01T03:45:12Z",
    action: "RECURRENT_HEALED_FROM_MEMORY",
    requiresSdeApproval: false,
    sdeApproved: false,
    patchSummary: "Auto-healed from memory: Increased pool size from 10 to 25 and added connection recycle timeout.",
    testPassProof: "Stress harness simulation verified zero dropped connections.",
    memoryHit: true
  }
];

export const DEMO_MEMORY_FIXTURES: RecurrentIncidentMemory[] = [
  {
    id: "MEM-DEP-01",
    patternSignature: "unpinned-dependency-requirements.txt",
    title: "Unpinned dependency pin enforcement (==)",
    severity: "LOW",
    rootCause: "Manifest contains unversioned package reference leading to non-deterministic build",
    solutionDiff: "--- a/requirements.txt\n+++ b/requirements.txt\n-acme-httpkit>=1.0\n+acme-httpkit==1.2.0",
    timesResolved: 4,
    firstSeenAt: "2026-10-15T03:12:00Z",
    lastAppliedAt: "2026-11-01T03:31:00Z"
  },
  {
    id: "MEM-DB-02",
    patternSignature: "db-connection-pool-exhaustion",
    title: "Database Connection Pool Exhaustion Mitigation",
    severity: "MEDIUM",
    rootCause: "Default pool size 10 starved during batch sync jobs",
    solutionDiff: "--- a/config/database.py\n+++ b/config/database.py\n-POOL_SIZE = 10\n+POOL_SIZE = 25\n+POOL_RECYCLE = 1800",
    timesResolved: 7,
    firstSeenAt: "2026-10-18T02:40:00Z",
    lastAppliedAt: "2026-11-01T03:45:12Z"
  }
];
