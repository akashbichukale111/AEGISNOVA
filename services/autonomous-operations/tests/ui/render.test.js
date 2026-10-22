'use strict';
const test = require('node:test');
const assert = require('node:assert');
const ui = require('../../aegisnova_ops/static/app.js');

const run = {id: 'run_1', status: 'WAITING_FOR_APPROVAL', step: 'WAITING_FOR_APPROVAL', idempotency_key: 'k', correlation_id: 'c1', attempts: 0, last_error: '<img src=x onerror=alert(1)>'};

test('workflow detail shows approval wait indicator, timeline, cancel action and escapes content', () => {
  const html = ui.renderRunDetail({run, timeline: [{type: 'run.transition', from_state: 'RUNNING', to_state: 'WAITING_FOR_APPROVAL', ts: '2026-01-01T00:00:00.000000Z', actor: 'system', detail: {}}],
    attempts: [], approval: {id: 'apr_1', status: 'PENDING', label: 'DEVELOPMENT/TEST decision - not production authorization'}, notifications: []});
  assert.match(html, /Waiting for governance approval/);
  assert.match(html, /RUNNING -&gt; WAITING_FOR_APPROVAL/);
  assert.match(html, /data-act="cancel"/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

test('approval inbox marks local decisions as development/test and offers dev buttons only for local governance', () => {
  const item = {id: 'apr_1', run_id: 'run_1', scope: 'ops:x', risk_level: 'low', requester: 'me', reason: 'r', expires_at: '2026-01-01T01:00:00.000000Z', status: 'PENDING', dev_only: true, label: 'DEVELOPMENT/TEST decision - not production authorization'};
  const local = ui.renderApprovals({items: [item], governance: {production: false, configured: true, reason: ''}});
  assert.match(local, /LOCAL DEVELOPMENT governance/); assert.match(local, /Grant \(dev\)/);
  const prod = ui.renderApprovals({items: [item], governance: {production: true, configured: true, reason: ''}});
  assert.doesNotMatch(prod, /Grant \(dev\)/); assert.doesNotMatch(prod, /LOCAL DEVELOPMENT governance/);
  const down = ui.renderApprovals({items: [item], governance: {production: true, configured: false, reason: 'missing env: UNWIND_BASE_URL'}});
  assert.match(down, /fail-closed/);
});

test('notification state distinguishes accepted from delivered and simulated from verified', () => {
  assert.match(ui.deliveryLabel({status: 'ACCEPTED'}), /delivery not confirmed/);
  assert.match(ui.deliveryLabel({status: 'DELIVERED', delivery_verified: false}), /simulated\/local receipt - not verified/);
  assert.match(ui.deliveryLabel({status: 'DELIVERED', delivery_verified: true}), /verified provider receipt/);
  const html = ui.renderNotifications([{id: 'n1', channel: 'email', mode: 'SIMULATED', status: 'UNKNOWN', destination_masked: 'a***@x.com', provider_message_id: null, attempts: 1, next_attempt_at: null, last_error: 'timeout'}]);
  assert.match(html, /SIMULATED/); assert.match(html, /UNKNOWN/); assert.match(html, /Send test to local sink/); assert.doesNotMatch(html, /a@x\.com/);
});

test('notification detail offers replay only for UNKNOWN/DEAD_LETTERED and simulated receipt only for non-real', () => {
  const base = {attempts: [], receipts: []};
  const unk = ui.renderNotifDetail({...base, notification: {id: 'n', status: 'UNKNOWN', mode: 'REAL', correlation_id: 'c'}});
  assert.match(unk, /data-replay/); assert.doesNotMatch(unk, /data-simrcpt/);
  const acc = ui.renderNotifDetail({...base, notification: {id: 'n', status: 'ACCEPTED', mode: 'SIMULATED', correlation_id: 'c'}});
  assert.match(acc, /data-simrcpt/); assert.doesNotMatch(acc, /data-replay/);
});

test('DLQ review lists items and detail shows history', () => {
  const q = {depth: 0, in_flight: 0, dlq_open: 1, retry_attempts: 3, oldest_pending_age_s: null, max_depth: 1000};
  const html = ui.renderQueues(q, [{id: 'dlq_1', kind: 'workflow', entity_id: 'run_1', error_class: 'transient_exhausted', status: 'OPEN', redrive_count: 0, created_at: '2026-01-01T00:00:00.000000Z'}]);
  assert.match(html, /transient_exhausted/); assert.match(html, /Unavailable/); assert.match(html, /Redrive OPEN items/);
  const d = ui.renderDlqDetail({id: 'dlq_1', status: 'OPEN', kind: 'workflow', entity_id: 'run_1', error_class: 'x', event_id: 'e', payload_hash: 'h', error: 'boom', attempt_history: [{attempt_no: 1}], related_events: []});
  assert.match(d, /Attempt history/); assert.match(d, /boom/);
});

test('integration status shows UNCONFIGURED with reason and env var names only', () => {
  const html = ui.renderSettings({items: [{name: 'whatsapp-cloud-api', state: 'UNCONFIGURED', reason: 'missing env: WHATSAPP_ACCESS_TOKEN', env_vars: ['WHATSAPP_ACCESS_TOKEN'], setup: 's'}]});
  assert.match(html, /UNCONFIGURED/); assert.match(html, /missing env: WHATSAPP_ACCESS_TOKEN/); assert.match(html, /Test \(read-only\)/);
});

test('overview shows Unavailable instead of fabricated zero', () => {
  const o = {runs_by_state: {queued: 0, failed: 2}, queue: {depth: 0, in_flight: 0, dlq_open: 0, retry_attempts: 0, oldest_pending_age_s: null}, worker_heartbeat: {age_s: null},
    notifications_by_channel: {}, providers: []};
  const html = ui.renderOverview(o);
  assert.equal((html.match(/<span class="muted">Unavailable<\/span>/g) || []).length, 2);
});

test('reliability view shows alarm explanation and unavailable state', () => {
  const html = ui.renderReliability([{name: 'A', state: 'UNAVAILABLE', metric: 'm', comparison: '>', threshold: 1, last_value: null, severity: 'critical', runbook: 'docs/x'}],
    [{alarm_name: 'A', state: 'RESOLVED', triggered_at: '2026-01-01T00:00:00.000000Z', resolved_at: '2026-01-01T00:05:00.000000Z', explanation: 'm = 2 breached'}]);
  assert.match(html, /UNAVAILABLE/); assert.match(html, /m = 2 breached/); assert.match(html, /RESOLVED/);
});
