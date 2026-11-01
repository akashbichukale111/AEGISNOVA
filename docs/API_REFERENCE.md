# AEGISNOVA REST API Contract Reference

This document provides the full REST API specification for AEGISNOVA's core control plane endpoints.

---

## 1. Copilot & 3 AM Patrol APIs

### `POST /api/copilot/chat`
Receives natural language instructions and GitHub repository targets, evaluates severity via AST & Security Classifier, and executes either zero-wakeup auto-resolution (LOW/MEDIUM) or UNWIND quarantined approval (HIGH/CRITICAL).

- **Request Body:**
  ```json
  {
    "message": "Fix SQL injection vulnerability in payments route",
    "repo_target": "akashbichukale111/AEGISNOVA"
  }
  ```

- **Response `200 OK` (CRITICAL / HIGH):**
  ```json
  {
    "message": {
      "id": "msg-1730419200000",
      "role": "assistant",
      "content": "🛡️ CRITICAL Severity Detected: SQL Injection vector discovered in payments handler...",
      "severity": "CRITICAL",
      "autonomyAction": "WAITING_FOR_SDE_APPROVAL",
      "executionPreview": {
        "diffSnippet": "--- a/src/payments.py\n+++ b/src/payments.py...",
        "testsPassed": 14,
        "totalTests": 14,
        "warrantDebitBp": 150,
        "requiresApproval": true
      }
    },
    "incident": {
      "id": "inc-critical-1730419200000",
      "severity": "CRITICAL",
      "action": "WAITING_FOR_SDE_APPROVAL",
      "requiresSdeApproval": true
    }
  }
  ```

- **Response `200 OK` (LOW / MEDIUM):**
  ```json
  {
    "message": {
      "role": "assistant",
      "content": "⚡ LOW Severity Auto-Resolved: Syntax drift resolved autonomously without waking SDE at 3:00 AM...",
      "severity": "LOW",
      "autonomyAction": "AUTO_RESOLVED_NO_SDE_WAKEUP"
    }
  }
  ```

---

### `POST /api/copilot/approve`
1-Click human countersignature under UNWIND authority for quarantined incidents.

- **Request Body:**
  ```json
  {
    "incident_id": "inc-critical-1730419200000",
    "approver": "SDE On-Call (Web UI)",
    "notes": "1-Click SDE verification approved from NightShift 3 AM Patrol"
  }
  ```

- **Response `200 OK`:**
  ```json
  {
    "success": true,
    "incident": {
      "id": "inc-critical-1730419200000",
      "action": "SDE_APPROVED_AND_EXECUTED",
      "sdeApproved": true
    },
    "governance": {
      "unwindDebitBp": 150,
      "attestationHash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    }
  }
  ```

---

## 2. Autonomous Engineering Studio APIs

### `POST /api/engineering/run`
Executes the full 12-Stage PCPR verification pipeline.

- **Request Body:**
  ```json
  {
    "repoTarget": {
      "id": "demo/payments-service",
      "name": "Payments Service",
      "path": "d:/AEGISNOVA",
      "defaultBranch": "main"
    },
    "issueTask": {
      "id": "task-101",
      "title": "Fix SQL injection in auth/login.py",
      "description": "Sanitize query parameters using prepared statements",
      "severity": "CRITICAL"
    }
  }
  ```

- **Response `200 OK`:**
  ```json
  {
    "success": true,
    "runId": "pcpr-run-1730419200",
    "status": "COMPLETED",
    "stagesCompleted": 12,
    "evidenceManifestHash": "8f8f963..."
  }
  ```

---

## 3. Evidence Intelligence APIs

### `POST /api/evidence/search`
Searches multi-source security intelligence via Tavily AI Search (300k quota).

- **Request Body:**
  ```json
  {
    "query": "CVE-2024-3094 xz utils backdoor remediation",
    "maxResults": 5
  }
  ```

- **Response `200 OK`:**
  ```json
  {
    "query": "CVE-2024-3094 xz utils backdoor remediation",
    "provider": "Tavily AI Search",
    "results": [
      {
        "title": "CVE-2024-3094 Advisory and Mitigation",
        "url": "https://nvd.nist.gov/vuln/detail/CVE-2024-3094",
        "snippet": "Vulnerability details, affected versions, and downgrade guidance.",
        "score": 0.98
      }
    ]
  }
  ```
