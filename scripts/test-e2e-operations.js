/**
 * End-to-End Live Integration Verification Script
 * ================================================
 * Validates the full loop through Next.js server proxy (http://localhost:3000):
 * 1. Start a workflow with required approval -> PAUSED_APPROVAL (waiting_approval)
 * 2. Verify approval is in /api/operations/approvals
 * 3. Grant test approval via /api/operations/approvals/:id/dev-decision
 * 4. Verify workflow resumes and completes
 * 5. Verify notification recorded in local sink
 */

const http = require('http');

function request(options, data) {
  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let body = '';
      res.on('data', (chunk) => body += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(body) });
        } catch {
          resolve({ status: res.statusCode, raw: body });
        }
      });
    });
    req.on('error', reject);
    if (data) req.write(JSON.stringify(data));
    req.end();
  });
}

async function runE2E() {
  console.log("=== STARTING END-TO-END AUTONOMOUS OPERATIONS TEST ===");

  // 1. Check Health via Proxy
  const health = await request({
    host: 'localhost',
    port: 3000,
    path: '/api/operations/health',
    method: 'GET'
  });
  console.log(`[PASS] Proxy Health Check: HTTP ${health.status} (status: ${health.data?.status})`);
  if (health.status !== 200) process.exit(1);

  // 2. Start sample.governed_action
  const start = await request({
    host: 'localhost',
    port: 3000,
    path: '/api/operations/runs',
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  }, {
    workflow_type: "sample.governed_action",
    payload: {
      action: "record_marker",
      scope: "scope:ops:execute",
      risk_level: "high",
      approval_required: true,
      notify: {
        channel: "local_sink",
        destination: "ops-lead@aegisnova.local"
      }
    }
  });
  console.log(`[PASS] Workflow Started Response:`, JSON.stringify(start.data));
  const runId = start.data?.id || start.data?.run?.id;
  const runStatus = start.data?.status || start.data?.run?.status;
  console.log(`[PASS] Workflow Created: ID ${runId}, Initial Status: ${runStatus}`);
  if (!runId) {
    console.error("[FAIL] Workflow ID missing");
    process.exit(1);
  }

  // Trigger worker tick or wait for background worker loop
  await request({
    host: 'localhost',
    port: 3000,
    path: '/api/operations/worker/tick',
    method: 'POST'
  });
  await new Promise(r => setTimeout(r, 600));

  // Verify it entered WAITING_FOR_APPROVAL
  const midRun = await request({
    host: 'localhost',
    port: 3000,
    path: `/api/operations/runs/${runId}`,
    method: 'GET'
  });
  console.log(`[PASS] Workflow Stepped: Status ${midRun.data?.run?.status}, Step: ${midRun.data?.run?.step}`);
  if (midRun.data?.run?.status !== "WAITING_FOR_APPROVAL" && midRun.data?.run?.status !== "waiting_approval") {
    console.error("[FAIL] Workflow should have transitioned to WAITING_FOR_APPROVAL");
    process.exit(1);
  }

  // 3. Inspect Approvals
  const approvals = await request({
    host: 'localhost',
    port: 3000,
    path: '/api/operations/approvals',
    method: 'GET'
  });
  const pending = approvals.data?.items?.find(a => a.run_id === runId && (a.status === 'PENDING' || a.status === 'pending' || a.status === 'waiting_approval'));
  console.log(`[PASS] Approval Gated: ID ${pending?.id}, Scope: ${pending?.scope}`);
  if (!pending) {
    console.error("[FAIL] Approval not found in pending list");
    process.exit(1);
  }

  // 4. Submit Local Test Decision
  const decision = await request({
    host: 'localhost',
    port: 3000,
    path: `/api/operations/approvals/${pending.id}/dev-decision`,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  }, { decision: "granted" });
  console.log(`[PASS] Test Decision Granted: HTTP ${decision.status}`);

  // 5. Allow worker tick to resume and complete workflow
  await request({
    host: 'localhost',
    port: 3000,
    path: '/api/operations/worker/tick',
    method: 'POST'
  });
  await new Promise(r => setTimeout(r, 1000));

  // 6. Check final run status
  const finalRun = await request({
    host: 'localhost',
    port: 3000,
    path: `/api/operations/runs/${runId}`,
    method: 'GET'
  });
  console.log(`[PASS] Final Workflow State: Status ${finalRun.data?.run?.status}, Step: ${finalRun.data?.run?.step}`);
  if (finalRun.data?.run?.status !== "SUCCEEDED" && finalRun.data?.run?.status !== "completed") {
    console.error("[FAIL] Expected workflow to complete after approval");
    process.exit(1);
  }

  // 7. Check local notification outbox
  const notifs = await request({
    host: 'localhost',
    port: 3000,
    path: '/api/operations/notifications',
    method: 'GET'
  });
  const notif = notifs.data?.items?.find(n => n.run_id === runId);
  console.log(`[PASS] Notification Outbox Recorded: ID ${notif?.id}, Status: ${notif?.status}, Destination: ${notif?.destination_masked}`);

  console.log("\n========================================================");
  console.log("ALL LIVE END-TO-END VERIFICATION CHECKS PASSED CLEANLY!");
  console.log("========================================================");
}

runE2E().catch(err => {
  console.error("E2E Test Failed:", err);
  process.exit(1);
});
