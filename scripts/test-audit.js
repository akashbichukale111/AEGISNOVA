const http = require('http');

const data = JSON.stringify({ url: 'demo/payments-service' });

const req = http.request({
  hostname: 'localhost',
  port: 3000,
  path: '/api/repo-intelligence/audit',
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Content-Length': data.length
  }
}, (res) => {
  let body = '';
  res.on('data', chunk => body += chunk);
  res.on('end', () => {
    console.log(`STATUS: ${res.statusCode}`);
    const json = JSON.parse(body);
    console.log(`REPORT ID: ${json.reportId}`);
    console.log(`REPO: ${json.architectureMap?.repoName}`);
    console.log(`LANGUAGES:`, json.architectureMap?.languages);
    console.log(`ENTRY POINTS:`, json.architectureMap?.entryPoints);
    console.log(`TEST RUNNERS:`, json.architectureMap?.testRunnersDiscovered);
    console.log(`MANIFESTS:`, json.architectureMap?.manifestsFound);
    console.log(`FINDINGS COUNT: ${json.findings?.length}`);
    json.findings?.forEach(f => {
      console.log(` - [${f.severity}] ${f.ruleId}: ${f.title} (${f.filePath}:${f.lineNumber || 0})`);
    });
  });
});

req.on('error', (e) => console.error(e));
req.write(data);
req.end();
