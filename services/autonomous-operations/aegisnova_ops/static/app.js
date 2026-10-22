/* AEGISNOVA Ops UI. No inline scripts (CSP). Pure render functions are exported for node tests. */
'use strict';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];});}
var STATUS_CLASS={SUCCEEDED:'ok',DELIVERED:'ok',ACCEPTED:'info',GRANTED:'ok',CLOSED:'ok',OK:'ok',CONFIGURED:'ok',
  FAILED:'bad',DEAD_LETTERED:'bad',REJECTED:'bad',REVOKED:'bad',EXPIRED:'bad',ALARM:'bad',OPEN:'bad',
  WAITING_FOR_APPROVAL:'warn',RETRY_WAIT:'warn',RETRYING:'warn',UNKNOWN:'warn',UNCONFIGURED:'warn',UNAVAILABLE:'warn',PENDING:'warn',SUPPRESSED:'warn',PAUSED:'warn',
  LOCAL:'info',SIMULATED:'info',RUNNING:'info',QUEUED:'info',SENDING:'info',CREATED:'info',HALF_OPEN:'warn'};
function badge(s){return '<span class="badge '+(STATUS_CLASS[s]||'')+'">'+esc(s)+'</span>';}
function val(v){return (v===null||v===undefined)?'<span class="muted">Unavailable</span>':esc(v);}
function fmtTime(t){return t?esc(String(t).replace('T',' ').replace(/\.\d+Z$/,'Z')):'-';}
function table(cols,rows,rowAttr){
  if(!rows.length)return '<p class="muted empty">Nothing to show yet.</p>';
  return '<table><thead><tr>'+cols.map(function(c){return '<th>'+esc(c[0])+'</th>';}).join('')+'</tr></thead><tbody>'+
    rows.map(function(r){return '<tr'+(rowAttr?' class="click" tabindex="0" '+rowAttr(r):'')+'>'+cols.map(function(c){return '<td>'+c[1](r)+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table>';
}
function deliveryLabel(n){
  if(n.status==='DELIVERED')return n.delivery_verified?'DELIVERED (verified provider receipt)':'DELIVERED (simulated/local receipt - not verified)';
  if(n.status==='ACCEPTED')return 'ACCEPTED by provider - delivery not confirmed';
  return n.status;
}
function renderOverview(o){
  var r=o.runs_by_state,q=o.queue,hb=o.worker_heartbeat;
  var cards=Object.keys(r).map(function(k){return '<div class="card"><div class="k">'+esc(k.replace(/_/g,' '))+'</div><div class="v">'+esc(r[k])+'</div></div>';}).join('');
  var ops=[['Queue depth',q.depth],['In flight',q.in_flight],['DLQ (open)',q.dlq_open],['Retry attempts',q.retry_attempts],
    ['Oldest pending (s)',q.oldest_pending_age_s==null?null:Math.round(q.oldest_pending_age_s)],
    ['Worker heartbeat age (s)',hb.age_s==null?null:Math.round(hb.age_s)]]
    .map(function(p){return '<div class="card"><div class="k">'+esc(p[0])+'</div><div class="v">'+val(p[1])+'</div></div>';}).join('');
  var ch=o.notifications_by_channel,crow=Object.keys(ch).map(function(c){return {channel:c,counts:ch[c]};});
  var nt=table([['Channel',function(x){return esc(x.channel);}],['States',function(x){return Object.keys(x.counts).map(function(s){return badge(s)+' '+esc(x.counts[s]);}).join(' ');}]],crow);
  var pv=table([['Provider',function(p){return esc(p.provider);}],['Circuit',function(p){return badge(p.state);}],['Last error',function(p){return esc(p.last_error||'-');}]],o.providers);
  return '<h1>Operations Overview</h1><p class="muted">Measured data only; unavailable metrics are shown as Unavailable.</p><div class="grid">'+cards+'</div><h2>Queue &amp; worker</h2><div class="grid">'+ops+'</div><h2>Notifications by channel</h2>'+nt+'<h2>Provider health</h2>'+(o.providers.length?pv:'<p class="muted">No provider calls recorded yet.</p>');
}
function renderRunsList(items){
  return table([['Run',function(r){return '<code>'+esc(r.id)+'</code>';}],['Type',function(r){return esc(r.workflow_type);}],['Status',function(r){return badge(r.status);}],
    ['Step',function(r){return esc(r.step);}],['Correlation',function(r){return '<code>'+esc(r.correlation_id)+'</code>';}],['Created',function(r){return fmtTime(r.created_at);}]],
    items,function(r){return 'data-run="'+esc(r.id)+'"';});
}
function renderRunDetail(d){
  var r=d.run,tl=d.timeline.map(function(e){return '<li><b>'+esc(e.type)+'</b> '+(e.from_state||e.to_state?esc((e.from_state||'')+' -> '+(e.to_state||'')):'')+' <span class="muted">'+fmtTime(e.ts)+' by '+esc(e.actor)+'</span>'+(e.detail&&Object.keys(e.detail).length?'<br><small class="muted">'+esc(JSON.stringify(e.detail))+'</small>':'')+'</li>';}).join('');
  var att=table([['#',function(a){return esc(a.attempt_no);}],['Step',function(a){return esc(a.step);}],['Outcome',function(a){return esc(a.outcome);}],['Error',function(a){return esc(a.error||'-');}],['Started',function(a){return fmtTime(a.started_at);}]],d.attempts);
  var ap=d.approval?'<p>Approval <code>'+esc(d.approval.id)+'</code> '+badge(d.approval.status)+' <span class="muted">'+esc(d.approval.label)+'</span></p>':'<p class="muted">No approval required.</p>';
  var nt=d.notifications.length?d.notifications.map(function(n){return '<p><code>'+esc(n.id)+'</code> '+badge(n.status)+' '+badge(n.mode)+'</p>';}).join(''):'<p class="muted">No notifications.</p>';
  var can=function(a){return '<button data-act="'+a+'" data-run="'+esc(r.id)+'"'+'>'+a[0].toUpperCase()+a.slice(1)+'</button>';};
  var btns=[];if(r.status==='QUEUED'||r.status==='RETRY_WAIT')btns.push(can('pause'));if(r.status==='PAUSED')btns.push(can('resume'));
  if(r.status==='FAILED')btns.push(can('retry'));if(['QUEUED','RUNNING','RETRY_WAIT','WAITING_FOR_APPROVAL','PAUSED'].indexOf(r.status)>=0)btns.push(can('cancel'));
  return '<h1>Run <code>'+esc(r.id)+'</code> '+badge(r.status)+'</h1>'+(r.status==='WAITING_FOR_APPROVAL'?'<div class="banner">Waiting for governance approval - the workflow will not proceed without a valid, scoped decision.</div>':'')+
   '<p class="muted">Step '+esc(r.step)+' | idempotency key <code>'+esc(r.idempotency_key)+'</code> | correlation <code>'+esc(r.correlation_id)+'</code> | attempts '+esc(r.attempts||0)+'</p>'+(r.last_error?'<div class="err">Last error: '+esc(r.last_error)+'</div>':'')+
   '<div class="bar">'+btns.join('')+'<button class="ghost" data-back="runs">Back to runs</button></div><div class="split"><div><h2>Timeline</h2><ul class="timeline">'+tl+'</ul></div><div><h2>Approval</h2>'+ap+'<h2>Attempts</h2>'+att+'<h2>Notifications</h2>'+nt+'</div></div>';
}
function renderApprovals(d){
  var banner=d.governance.production?'':'<div class="banner">LOCAL DEVELOPMENT governance is active. Decisions here are test-only and are not production authorization.</div>';
  var why=d.governance.configured?'':'<div class="err">Governance provider unavailable: '+esc(d.governance.reason)+'. Workflows needing approval stay WAITING (fail-closed).</div>';
  var t=table([['Approval',function(a){return '<code>'+esc(a.id)+'</code>';}],['Run',function(a){return '<code>'+esc(a.run_id)+'</code>';}],['Scope',function(a){return esc(a.scope);}],['Risk',function(a){return badge(a.risk_level);}],
    ['Requester / reason',function(a){return esc((a.requester||'-')+' / '+(a.reason||'-'));}],['Expires',function(a){return fmtTime(a.expires_at);}],['Status',function(a){return badge(a.status)+(a.blocked_reason?'<br><small class="muted">'+esc(a.blocked_reason)+'</small>':'');}],
    ['Decision',function(a){return a.status==='PENDING'&&!d.governance.production?'<button data-dec="granted" data-ap="'+esc(a.id)+'">Grant (dev)</button> <button class="danger" data-dec="rejected" data-ap="'+esc(a.id)+'">Reject (dev)</button>':(a.status==='GRANTED'&&!d.governance.production?'<button class="danger" data-dec="revoked" data-ap="'+esc(a.id)+'">Revoke (dev)</button>':esc(a.label||''));}]],d.items);
  return '<h1>Approval Inbox</h1>'+banner+why+t;
}
function renderNotifications(items){
  return '<h1>Notifications</h1><div class="bar"><button id="sendTest">Send test to local sink</button><button id="realSend" class="ghost">Real send...</button></div>'+
  table([['ID',function(n){return '<code>'+esc(n.id)+'</code>';}],['Channel',function(n){return esc(n.channel);}],['Mode',function(n){return badge(n.mode);}],['Status',function(n){return badge(n.status)+'<br><small class="muted">'+esc(deliveryLabel(n))+'</small>';}],
    ['To',function(n){return esc(n.destination_masked);}],['Provider msg ID',function(n){return esc(n.provider_message_id||'-');}],['Attempts',function(n){return esc(n.attempts);}],['Next retry',function(n){return fmtTime(n.next_attempt_at);}],['Last error',function(n){return esc(n.last_error||'-');}]],items,function(n){return 'data-notif="'+esc(n.id)+'"';});
}
function renderNotifDetail(d){
  var n=d.notification;
  return '<h1>Notification <code>'+esc(n.id)+'</code> '+badge(n.status)+' '+badge(n.mode)+'</h1><p class="muted">'+esc(deliveryLabel(n))+' | run '+esc(n.run_id||'-')+' | correlation '+esc(n.correlation_id)+'</p>'+
   '<div class="bar"><button class="ghost" data-back="notifications">Back</button>'+((n.status==='UNKNOWN'||n.status==='DEAD_LETTERED')?'<button class="danger" data-replay="'+esc(n.id)+'">Replay (admin)</button>':'')+((n.mode!=='REAL'&&n.status==='ACCEPTED')?'<button data-simrcpt="'+esc(n.id)+'">Simulate delivered receipt</button>':'')+'</div>'+
   '<h2>Attempts</h2>'+table([['#',function(a){return esc(a.attempt_no);}],['Provider',function(a){return esc(a.provider);}],['Outcome',function(a){return esc(a.outcome);}],['Error',function(a){return esc(a.error||'-');}],['Started',function(a){return fmtTime(a.started_at);}]],d.attempts)+
   '<h2>Receipts</h2>'+table([['Status',function(r){return esc(r.status);}],['Verified',function(r){return esc(r.verified?'yes':'no');}],['Source',function(r){return esc(r.source);}],['Note',function(r){return esc(r.note||(r.applied?'applied':'-'));}],['Received',function(r){return fmtTime(r.received_at);}]],d.receipts);
}
function renderQueues(q,dlq){
  var cards=[['Depth',q.depth],['In flight',q.in_flight],['DLQ open',q.dlq_open],['Retry attempts',q.retry_attempts],['Oldest pending (s)',q.oldest_pending_age_s==null?null:Math.round(q.oldest_pending_age_s)],['Max depth',q.max_depth]].map(function(p){return '<div class="card"><div class="k">'+esc(p[0])+'</div><div class="v">'+val(p[1])+'</div></div>';}).join('');
  var t=table([['DLQ item',function(d){return '<code>'+esc(d.id)+'</code>';}],['Kind',function(d){return esc(d.kind);}],['Entity',function(d){return '<code>'+esc(d.entity_id)+'</code>';}],['Error class',function(d){return esc(d.error_class);}],['Status',function(d){return badge(d.status);}],['Redrives',function(d){return esc(d.redrive_count);}],['Created',function(d){return fmtTime(d.created_at);}]],dlq,function(d){return 'data-dlq="'+esc(d.id)+'"';});
  return '<h1>Queues &amp; Dead Letters</h1><div class="grid">'+cards+'</div><h2>Dead-letter items</h2><div class="bar"><button id="redriveDry">Dry-run redrive of all OPEN items</button><button id="redriveGo" class="danger">Redrive OPEN items...</button></div>'+t;
}
function renderDlqDetail(d){
  return '<h1>DLQ <code>'+esc(d.id)+'</code> '+badge(d.status)+'</h1><p class="muted">'+esc(d.kind)+' '+esc(d.entity_id)+' | error class '+esc(d.error_class)+' | event id '+esc(d.event_id)+' | payload hash <code>'+esc(d.payload_hash)+'</code></p><div class="err">'+esc(d.error||'')+'</div><div class="bar"><button class="ghost" data-back="queues">Back</button></div><h2>Attempt history</h2><pre>'+esc(JSON.stringify(d.attempt_history,null,2))+'</pre><h2>Related events</h2><ul class="timeline">'+d.related_events.map(function(e){return '<li>'+esc(e.type)+' <span class="muted">'+fmtTime(e.ts)+'</span></li>';}).join('')+'</ul>';
}
function renderReliability(al,ev){
  var t=table([['Alarm',function(a){return esc(a.name);}],['State',function(a){return badge(a.state);}],['Metric',function(a){return esc(a.metric);}],['Threshold',function(a){return esc(a.comparison+' '+a.threshold);}],['Current',function(a){return val(a.last_value);}],['Severity',function(a){return esc(a.severity);}],['Runbook',function(a){return esc(a.runbook);}]],al);
  var h=table([['Alarm',function(e){return esc(e.alarm_name);}],['State',function(e){return badge(e.state);}],['Triggered',function(e){return fmtTime(e.triggered_at);}],['Resolved',function(e){return fmtTime(e.resolved_at);}],['Why',function(e){return esc(e.explanation);}]],ev);
  return '<h1>Reliability &amp; Alerts</h1><div class="bar"><button id="evalAlarms">Evaluate alarms now</button></div><h2>Alarm rules</h2>'+t+'<h2>Alarm history</h2>'+h;
}
function renderEvents(items){
  return '<h1>Event Log</h1><div class="bar"><input id="evq" placeholder="search type / id / correlation" aria-label="Search events"><button id="evGo">Search</button></div>'+
   table([['Seq',function(e){return esc(e.seq);}],['Time',function(e){return fmtTime(e.ts);}],['Type',function(e){return esc(e.type);}],['Entity',function(e){return esc(e.entity_type+' '+e.entity_id);}],['Transition',function(e){return esc((e.from_state||'')+(e.to_state?' -> '+e.to_state:''));}],['Actor',function(e){return esc(e.actor);}]],items);
}
function renderSettings(d){
  return '<h1>Settings / Integrations</h1><p class="muted">Variable names only. Credential values are never displayed.</p>'+
   table([['Integration',function(i){return esc(i.name);}],['State',function(i){return badge(i.state);}],['Why',function(i){return esc(i.reason);}],['Env vars',function(i){return esc((i.env_vars||[]).join(', '));}],['Setup',function(i){return esc(i.setup||'');}],['Test',function(i){return '<button class="ghost" data-test="'+esc(i.name)+'">Test (read-only)</button>';}]],d.items);
}
function renderRunsPage(items){
  return '<h1>Workflow Runs</h1><div class="bar"><input id="rq" placeholder="run / correlation / idempotency" aria-label="Search runs"><select id="rs" aria-label="Status filter"><option value="">any status</option>'+
   ['QUEUED','RUNNING','WAITING_FOR_APPROVAL','RETRY_WAIT','PAUSED','SUCCEEDED','FAILED','DEAD_LETTERED','CANCELLED'].map(function(s){return '<option>'+s+'</option>';}).join('')+
   '</select><input id="rsince" type="datetime-local" aria-label="Created since"><button id="rgo">Filter</button></div>'+
   '<form id="startForm" class="bar"><select id="swf" aria-label="Workflow"><option>sample.governed_action</option></select><label><input type="checkbox" id="sapp" checked> require approval</label><select id="ssim" aria-label="Failure simulation"><option value="0">no failure</option><option value="1">1 transient failure</option><option value="9">exhaust retries (DLQ)</option></select><button type="submit">Start sample workflow</button></form>'+renderRunsList(items);
}
if(typeof module!=='undefined'){module.exports={esc:esc,badge:badge,renderOverview:renderOverview,renderRunDetail:renderRunDetail,renderApprovals:renderApprovals,renderNotifications:renderNotifications,renderNotifDetail:renderNotifDetail,renderQueues:renderQueues,renderDlqDetail:renderDlqDetail,renderReliability:renderReliability,renderSettings:renderSettings,renderRunsList:renderRunsList,deliveryLabel:deliveryLabel};}
if(typeof document!=='undefined'){(function(){
  var main=document.getElementById('main'),view='overview',timer=null;
  function tok(){return sessionStorage.getItem('aegis_token')||'';}
  function toast(m,bad){var d=document.createElement('div');d.textContent=m;if(bad)d.style.borderColor='var(--bad)';document.getElementById('toast').appendChild(d);setTimeout(function(){d.remove();},5000);}
  function api(method,path,body){
    return fetch(path,{method:method,headers:{'Authorization':'Bearer '+tok(),'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}).then(function(r){
      return r.json().catch(function(){return {};}).then(function(j){if(!r.ok){var e=new Error((j.error&&j.error.message)||('HTTP '+r.status));e.status=r.status;e.code=j.error&&j.error.code;throw e;}return j;});});
  }
  function confirmDlg(html,ok){return new Promise(function(res){var d=document.getElementById('dlg');document.getElementById('dlgBody').innerHTML=html;document.getElementById('dlgOk').textContent=ok||'Confirm';d.onclose=function(){res(d.returnValue==='ok');};d.showModal();});}
  function show(html){main.innerHTML=html;}
  function fail(e){show('<div class="err" role="alert">'+esc(e.status===401?'Authentication required: paste a dev token in the sidebar.':e.message)+'</div><div class="bar"><button id="retryLoad">Retry</button></div>');var b=document.getElementById('retryLoad');if(b)b.onclick=function(){load(view);};}
  function header(){
    api('GET','/api/overview').then(function(o){var e=o.environment;document.getElementById('envBadge').textContent=e.label+' | '+e.detail;
      var g=document.getElementById('govBadge');g.textContent=e.governance_production?('governance: '+e.governance):'governance: LOCAL DEV (test-only)';g.className='badge '+(e.governance_production?'ok':'warn');}).catch(function(){document.getElementById('envBadge').textContent='Not connected';});
  }
  function load(v,arg){
    view=v;[].forEach.call(document.querySelectorAll('#nav button'),function(b){b.classList.toggle('active',b.dataset.view===v);});
    show('<p class="muted">Loading...</p>');header();
    var p;
    if(v==='overview')p=api('GET','/api/overview').then(function(o){show(renderOverview(o));});
    else if(v==='runs')p=api('GET','/api/runs'+(arg||'')).then(function(d){show(renderRunsPage(d.items));wireRuns();});
    else if(v==='run')p=api('GET','/api/runs/'+arg).then(function(d){show(renderRunDetail(d));wireRunDetail();});
    else if(v==='approvals')p=api('GET','/api/approvals').then(function(d){show(renderApprovals(d));wireApprovals();});
    else if(v==='notifications')p=api('GET','/api/notifications').then(function(d){show(renderNotifications(d.items));wireNotifs();});
    else if(v==='notif')p=api('GET','/api/notifications/'+arg).then(function(d){show(renderNotifDetail(d));wireNotifDetail();});
    else if(v==='queues')p=Promise.all([api('GET','/api/queue'),api('GET','/api/dlq')]).then(function(r){show(renderQueues(r[0],r[1].items));wireQueues();});
    else if(v==='dlq')p=api('GET','/api/dlq/'+arg).then(function(d){show(renderDlqDetail(d));wireBack();});
    else if(v==='reliability')p=Promise.all([api('GET','/api/alarms'),api('GET','/api/alarm-events')]).then(function(r){show(renderReliability(r[0].items,r[1].items));var b=document.getElementById('evalAlarms');b.onclick=function(){api('POST','/api/alarms/evaluate',{}).then(function(){toast('Alarms evaluated');load('reliability');}).catch(function(e){toast(e.message,1);});};});
    else if(v==='events')p=api('GET','/api/events'+(arg||'')).then(function(d){show(renderEvents(d.items));document.getElementById('evGo').onclick=function(){load('events','?q='+encodeURIComponent(document.getElementById('evq').value));};});
    else if(v==='settings')p=api('GET','/api/integrations').then(function(d){show(renderSettings(d));[].forEach.call(main.querySelectorAll('[data-test]'),function(b){b.onclick=function(){api('POST','/api/integrations/'+b.dataset.test+'/test',{}).then(function(r){toast(b.dataset.test+': '+(r.ok?'OK':'not OK')+' - '+r.reason,!r.ok);}).catch(function(e){toast(e.message,1);});};});});
    p.catch(fail);
  }
  function wireBack(){[].forEach.call(main.querySelectorAll('[data-back]'),function(b){b.onclick=function(){load(b.dataset.back);};});}
  function rowClicks(attr,v){[].forEach.call(main.querySelectorAll('['+attr+']'),function(r){var go=function(){load(v,r.getAttribute(attr));};r.onclick=go;r.onkeydown=function(e){if(e.key==='Enter')go();};});}
  function wireRuns(){
    rowClicks('data-run','run');
    document.getElementById('rgo').onclick=function(){var q=new URLSearchParams();var a=document.getElementById('rq').value,s=document.getElementById('rs').value,t=document.getElementById('rsince').value;if(a)q.set('q',a);if(s)q.set('status',s);if(t)q.set('since',t.replace(/$/,':00.000000Z'));load('runs','?'+q.toString());};
    document.getElementById('startForm').onsubmit=function(ev){ev.preventDefault();var n=+document.getElementById('ssim').value;
      api('POST','/api/runs',{workflow_type:'sample.governed_action',payload:{approval_required:document.getElementById('sapp').checked,reason:'sample run from UI',simulate:{fail_times:n,kind:'transient'}}}).then(function(r){toast('Started '+r.run.id);load('runs');}).catch(function(e){toast(e.message,1);});};
  }
  function wireRunDetail(){wireBack();[].forEach.call(main.querySelectorAll('[data-act]'),function(b){b.onclick=function(){var act=b.dataset.act,id=b.dataset.run;
    var go=function(){api('POST','/api/runs/'+id+'/'+act,act==='cancel'?{confirm:true}:{}).then(function(){toast(act+' ok');load('run',id);}).catch(function(e){toast(e.message,1);});};
    if(act==='cancel')confirmDlg('<b>Cancel run '+esc(id)+'?</b><p>Pending queue messages are closed. This cannot be undone.</p>','Cancel run').then(function(ok){if(ok)go();});else go();};});}
  function wireApprovals(){[].forEach.call(main.querySelectorAll('[data-dec]'),function(b){b.onclick=function(){confirmDlg('<b>Record DEVELOPMENT decision: '+esc(b.dataset.dec)+'</b><p>This is a local test decision, not production authorization.</p>','Record').then(function(ok){if(!ok)return;api('POST','/api/approvals/'+b.dataset.ap+'/dev-decision',{decision:b.dataset.dec}).then(function(){toast('decision recorded (dev)');load('approvals');}).catch(function(e){toast(e.message,1);});});};});}
  function wireNotifs(){rowClicks('data-notif','notif');
    document.getElementById('sendTest').onclick=function(){api('POST','/api/notifications/test',{channel:'local_sink',destination:'ops-sink@local.test'}).then(function(){toast('queued to LOCAL sink (no external send)');load('notifications');}).catch(function(e){toast(e.message,1);});};
    document.getElementById('realSend').onclick=function(){var ch=prompt('Channel for REAL send (email, sms, whatsapp)');if(!ch)return;var dest=prompt('Destination (must be allow-listed)');if(!dest)return;
      api('POST','/api/notifications/preview-real',{channel:ch,destination:dest}).then(function(p){
        confirmDlg('<b>REAL send preview</b><p>Provider: '+esc(p.provider)+' ('+(p.configured?'configured':'UNCONFIGURED: '+esc(p.reason))+')</p><p>Destination: <code>'+esc(p.destination_preview)+'</code></p><p>Message: '+esc(p.message_preview)+'</p><p>'+esc(p.warning)+'</p>','Send for real').then(function(ok){if(!ok)return;
          api('POST','/api/notifications/send-real',{channel:ch,destination:dest,confirm:'SEND',confirm_destination:dest}).then(function(){toast('queued for real send');load('notifications');}).catch(function(e){toast(e.message,1);});});}).catch(function(e){toast(e.message,1);});};}
  function wireNotifDetail(){wireBack();[].forEach.call(main.querySelectorAll('[data-replay]'),function(b){b.onclick=function(){confirmDlg('<b>Replay notification?</b><p>A new attempt is created; for UNKNOWN outcomes this may duplicate a message.</p>','Replay').then(function(ok){if(ok)api('POST','/api/notifications/'+b.dataset.replay+'/replay',{confirm:true}).then(function(){toast('queued for replay');load('notifications');}).catch(function(e){toast(e.message,1);});});};});
    [].forEach.call(main.querySelectorAll('[data-simrcpt]'),function(b){b.onclick=function(){api('POST','/api/dev/simulate-receipt',{notification_id:b.dataset.simrcpt,status:'delivered'}).then(function(r){toast('simulated receipt: '+r.result);load('notif',b.dataset.simrcpt);}).catch(function(e){toast(e.message,1);});};});}
  function wireQueues(){rowClicks('data-dlq','dlq');
    function ids(){return api('GET','/api/dlq?status=OPEN').then(function(d){return d.items.map(function(x){return x.id;}).slice(0,10);});}
    document.getElementById('redriveDry').onclick=function(){ids().then(function(i){return api('POST','/api/dlq/redrive',{ids:i,dry_run:true});}).then(function(r){toast('dry run: '+r.plan.filter(function(p){return p.eligible;}).length+' eligible of '+r.plan.length);}).catch(function(e){toast(e.message,1);});};
    document.getElementById('redriveGo').onclick=function(){ids().then(function(i){if(!i.length){toast('No OPEN dead letters');return;}confirmDlg('<b>Redrive '+i.length+' dead-letter item(s)?</b><p>Original event identity is preserved; a new attempt is recorded. Admin-only, rate-limited, audited.</p>','Redrive').then(function(ok){if(ok)api('POST','/api/dlq/redrive',{ids:i,dry_run:false,confirm:true}).then(function(r){toast('redriven '+r.redriven.length);load('queues');}).catch(function(e){toast(e.message,1);});});});};}
  document.getElementById('nav').onclick=function(e){var b=e.target.closest('button');if(b)load(b.dataset.view);};
  document.getElementById('refresh').onclick=function(){load(view);};
  document.getElementById('saveToken').onclick=function(){sessionStorage.setItem('aegis_token',document.getElementById('token').value.trim());document.getElementById('token').value='';toast('Token stored for this tab');load(view);};
  load('overview');
  timer=setInterval(function(){if(view==='overview'||view==='queues')load(view);},10000);
})();}
