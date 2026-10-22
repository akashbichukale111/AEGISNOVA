const http = require('http');

const runPayload = JSON.stringify({
  repoTarget: {
    id: "demo/payments-service",
    name: "payments-service",
    path: "services/nightshift-sde/fixtures/demo-repos/payments-service",
    defaultBranch: "main",
    testCommand: "python -m unittest discover -s tests",
    buildManifest: "requirements.txt",
    isMonitored: true
  },
  issueTask: {
    id: "TASK-TEST-01",
    title: "Upgrade acme-yamlish serializer and verify unit test suite",
    description: "Fix CVE-2026-8812 vulnerability",
    targetRepoId: "demo/payments-service",
    acceptanceCriteria: [
      "Mitigate unsafe deserialization in requirements.txt",
      "Pass unit tests in tests/test_app.py",
      "Verify zero secret leaks"
    ],
    severity: "CRITICAL",
    autonomyMode: "PATCH_AND_VERIFY",
    allowHighRiskWrites: true
  }
});

const req = http.request({
  hostname: 'localhost',
  port: 3000,
  path: '/api/engineering/run',
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Content-Length': runPayload.length
  }
}, (res) => {
  let body = '';
  res.on('data', chunk => body += chunk);
  res.on('end', () => {
    console.log(`LAUNCH STATUS: ${res.statusCode}`);
    const json = JSON.parse(body);
    const runId = json.run?.id;
    console.log(`RUN ID: ${runId}`);
    console.log(`STATUS: ${json.run?.status}`);
    
    // Poll for completion
    let attempts = 0;
    const poll = setInterval(() => {
      attempts++;
      http.get(`http://localhost:3000/api/engineering/status?runId=${runId}`, (pRes) => {
        let pBody = '';
        pRes.on('data', c => pBody += c);
        pRes.on('end', () => {
          const pData = JSON.parse(pBody);
          console.log(`[POLL #${attempts}] Status: ${pData.runStatus} | Step: ${pData.currentStepIndex}/12`);
          if (pData.runStatus === 'READY_FOR_REVIEW' || pData.runStatus === 'FAILED' || attempts > 15) {
            clearInterval(poll);
            console.log("=== MANIFEST RESULT ===");
            console.log("Manifest Hash:", pData.manifest?.manifestHash);
            console.log("Verifier Verdict:", pData.manifest?.verifierVerdict);
            console.log("Test Passed:", pData.manifest?.testResults?.passed, "/", pData.manifest?.testResults?.total);
            console.log("UNWIND Debit:", pData.manifest?.unwindWarrantDebitBp, "bp");
            console.log("PR Status:", pData.manifest?.pullRequestResult?.status);
          }
        });
      });
    }, 700);
  });
});

req.write(runPayload);
req.end();
