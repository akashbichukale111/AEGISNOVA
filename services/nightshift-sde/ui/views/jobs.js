// B. Live Job Observatory (+ job list). Actions are rendered from the server's `actions` list: disabled with the server's reason.
import { h, api, qs, panel, pill, btn, kv, table, pager, empty, errorBox, dur, rel, absTime, label, short, mono, copyable, toast, confirmDialog, select, sevBadge, ApiError, num, uuid } from "../lib.js";
import { icon } from "../icons.js";
import { miniTrack } from "./overview.js";

const STATES = ["CREATED", "QUEUED", "VALIDATING", "SNAPSHOTTING", "INSPECTING", "RESEARCHING", "EVIDENCE_REVIEW", "RISK_ASSESSMENT", "WAITING_FOR_APPROVAL", "READY_TO_EXECUTE", "EXECUTING", "TESTING", "INDEPENDENT_VERIFICATION", "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "RETRY_WAIT", "PAUSED", "CANCEL_REQUESTED", "CANCELLED", "EXPIRED", "DEAD_LETTER"];
const TERMINAL = new Set(["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED", "EXPIRED", "DEAD_LETTER"]);

export default function (ctx) {
  return ctx.params.id ? observatory(ctx, ctx.params.id) : list(ctx);
}

// ------------------------------------------------------------------------------------------------------- list
function list(ctx) {
  const q = ctx.query;
  const box = h("div");
  const search = h("input", { class: "inp", type: "search", placeholder: "Search id, correlation, requester", value: q.q || "", "aria-label": "Search jobs", onkeydown: (e) => { if (e.key === "Enter") ctx.setQuery({ q: e.target.value, offset: "" }, false); } });
  const bar = h("div", { class: "toolbar" },
    h("div", { class: "search" }, icon("search", 14), search),
    select([["", "Any state"], ...STATES.map((s) => [s, label(s)])], q.state, (v) => ctx.setQuery({ state: v, offset: "" }), "Filter by state"),
    select([["", "Any trigger"], ...["schedule", "manual", "webhook", "replay"].map((s) => [s, label(s)])], q.trigger, (v) => ctx.setQuery({ trigger: v, offset: "" }), "Filter by trigger"),
    select([["", "Any outcome"], ...["repair_verified", "investigation_only", "no_findings", "repair_blocked", "repair_rejected", "repair_revoked", "approval_expired", "dead_lettered", "failed", "cancelled", "expired"].map((s) => [s, label(s)])], q.outcome, (v) => ctx.setQuery({ outcome: v, offset: "" }), "Filter by outcome"),
    btn("Clear", { small: true, onclick: () => ctx.setQuery({ q: "", state: "", trigger: "", outcome: "", repo_id: "", offset: "" }, false) }));
  const body = h("div");
  const page = panel("Jobs", h("div", bar, body), { sub: "durable job records" });
  const limit = 25, offset = Number(q.offset || 0);
  ctx.live(body, () => api("GET", "/api/jobs" + qs({ q: q.q, state: q.state, trigger: q.trigger, outcome: q.outcome, repo_id: q.repo_id, schedule_id: q.schedule_id, limit, offset })), (d, refresh) =>
    d.items.length ? h("div", table([
      { h: "Job", f: (j) => h("a", { class: "mono", href: `#/jobs/${j.id}` }, short(j.id, 16)) },
      { h: "State", f: (j) => pill(j.state) }, { h: "Outcome", f: (j) => (j.outcome ? pill(j.outcome, label(j.outcome)) : h("span", { class: "mute" }, "—")) },
      { h: "Trigger", f: (j) => label(j.trigger_type) }, { h: "Write", f: (j) => (j.allow_repair ? pill("pending", "capable") : h("span", { class: "mute" }, "read-only")) },
      { h: "Attempt", f: (j) => `${j.attempt}${j.failed_attempts ? ` (${j.failed_attempts} failed)` : ""}`, cls: "num" },
      { h: "Last progress", f: (j) => h("span", { title: absTime(j.last_progress_at) }, rel(j.last_progress_at)) }, { h: "Created", f: (j) => h("span", { title: absTime(j.created_at) }, rel(j.created_at)) },
    ], d.items, { aria: "Jobs", rowClass: (j) => (["FAILED", "DEAD_LETTER"].includes(j.state) ? "bad" : ["WAITING_FOR_APPROVAL", "RETRY_WAIT", "PAUSED"].includes(j.state) ? "attn" : "") }), pager(d, (o) => ctx.setQuery({ offset: o }, false)))
      : empty("No jobs match", q.state || q.q || q.trigger || q.outcome ? "Try clearing filters." : "No jobs have been created yet. Trigger an inspection from Repository Fleet."), { ms: 5000 });
  return page;
}

// ------------------------------------------------------------------------------------------------------- observatory
function observatory(ctx, id) {
  const root = h("div");
  ctx.live(root, () => api("GET", `/api/jobs/${id}`), (d, refresh) => detail(d, refresh), { ms: 3000 });
  return root;
}

async function act(d, action, refresh, opts = {}) {
  const dangerous = ["cancel", "revoke", "reject", "replay"].includes(action);
  if (opts.confirm !== false) {
    const r = await confirmDialog({ title: `${label(action)} job ${short(d.job.id, 14)}?`, body: opts.body || confirmText(action), confirm: label(action), danger: dangerous, input: ["approve", "reject", "revoke"].includes(action) ? "Note for the audit trail (optional)" : null });
    if (!r) return;
    opts.note = r.note;
  }
  try {
    if (["approve", "reject", "revoke"].includes(action)) {
      const a = opts.approval;
      await api("POST", `/api/approvals/${a.id}/${action}`, { note: opts.note || "" });
    } else await api("POST", `/api/jobs/${d.job.id}/${action}`, opts.body ? undefined : {});
    toast(`${label(action)} applied`); refresh();
  } catch (e) { toast(`${label(action)} refused: ${e.message}${e.corr ? " (" + e.corr + ")" : ""}`, "bad"); refresh(); }
}
const confirmText = (a) => ({
  cancel: "Cancellation stops all future actions. A running worker winds down at its next safe point.",
  pause: "The job will stop at the next safe point and can be resumed from its last valid checkpoint.",
  resume: "The job is re-queued. Base commit, policy and evidence are re-verified before any further stage.",
  retry: "Skips the remaining backoff. The retry budget is NOT reset and approval gates still apply.",
  replay: "Creates a NEW linked job. The original job and its history stay untouched. Replay cannot bypass approval.",
  approve: "Approve exactly the scope shown: this repository, base commit, paths and diff. Any scope change invalidates it.",
  reject: "The repair will not run. Nothing is changed.",
  revoke: "Revokes the grant immediately. Any future write stage is blocked.",
}[a] || "Proceed?");

function detail(d, refresh) {
  const j = d.job, tl = d.transitions;
  const actions = d.actions;
  const stale = d.lease.live === false && j.lease_owner && !TERMINAL.has(j.state);
  const header = h("div", { class: "panel" }, h("div", { class: "panel-b stack" },
    h("div", { class: "row" }, h("a", { href: "#/jobs", class: "mute" }, "Jobs ›"), h("h2", { class: "mono" }, j.id), pill(j.state), j.outcome && pill(j.outcome, label(j.outcome)), j.allow_repair ? pill("pending", "write-capable") : pill("ok", "read-only"), h("span", { class: "grow" }),
      actions.filter((a) => !["approve", "reject", "revoke"].includes(a.action)).map((a) => btn(label(a.action), { small: true, ic: { pause: "pause", resume: "play", cancel: "stop", retry: "refresh", replay: "rewind" }[a.action], kind: a.action === "cancel" ? "danger" : "ghost", disabled: !a.enabled, reason: a.reason, onclick: () => act(d, a.action, refresh) }))),
    miniTrack(j.state),
    h("div", { class: d.explanation && ["FAILED", "DEAD_LETTER", "EXPIRED"].includes(j.state) ? "note bad" : j.state === "WAITING_FOR_APPROVAL" ? "note warn" : "note" },
      h("strong", d.explanation.summary), h("div", { class: "mute" }, "Next: ", d.explanation.next_step), h("div", { class: "mute" }, d.explanation.method)),
    stale && h("div", { class: "note warn" }, "The worker lease has expired — the watchdog will reclaim it and resume from the last valid checkpoint.")));

  const timeline = panel("State machine timeline", h("ul", { class: "tl" }, tl.map((t, i) => h("li", { class: "t-" + (["FAILED", "DEAD_LETTER", "EXPIRED"].includes(t.to_state) ? "bad" : ["COMPLETED", "COMPLETED_WITH_WARNINGS"].includes(t.to_state) ? "good" : ["WAITING_FOR_APPROVAL", "RETRY_WAIT", "PAUSED"].includes(t.to_state) ? "warn" : "") },
    h("div", { class: "row" }, pill(t.to_state), h("span", { class: "mute" }, t.from_state ? "from " + label(t.from_state) : "created"), h("span", { class: "mono mute" }, t.reason_code)),
    h("div", { class: "m mute" }, `${absTime(t.at)} · ${t.actor} (${t.source}) · attempt ${t.attempt} · fence ${t.fence}${i + 1 < tl.length || !TERMINAL.has(j.state) ? "" : ""}`),
    d.stage_durations_seconds[t.to_state] !== undefined && i === tl.findIndex((x) => x.to_state === t.to_state) ? h("div", { class: "m mute" }, `total time in ${label(t.to_state)}: ${dur(d.stage_durations_seconds[t.to_state])}`) : null,
    t.detail && t.detail !== "{}" && h("div", { class: "m mono mute" }, typeof t.detail === "string" ? t.detail.slice(0, 240) : JSON.stringify(t.detail).slice(0, 240))))), { sub: `${tl.length} persisted transition(s) · server time ${absTime(d.server_time)}` });

  const info = panel("Context", h("div", { class: "panel-b" }, kv([
    ["Repository", h("a", { href: `#/fleet` }, short(j.repo_id, 14), "")], ["Base commit", j.base_commit ? copyable(j.base_commit, short(j.base_commit, 12)) : "—"], ["Base tree", j.base_tree ? mono(short(j.base_tree, 16)) : "—"],
    ["Trigger", `${label(j.trigger_type)}${j.schedule_id ? " · schedule " + short(j.schedule_id, 12) : ""}`], ["Requested by", j.requested_by], ["Correlation ID", copyable(j.correlation_id)],
    ["Workflow / policy", `${j.workflow_version} · ${j.policy_name} v${j.policy_version ?? "—"}`], ["Priority", String(j.priority)],
    ["Created", absTime(j.created_at)], ["Last progress", `${rel(j.last_progress_at)}${j.last_progress_note ? " — " + j.last_progress_note : ""}`], ["Deadline", absTime(j.deadline_at)],
    j.replay_of && ["Replay of", h("a", { class: "mono", href: `#/jobs/${j.replay_of}` }, short(j.replay_of, 14))],
    d.replays.length && ["Replays", d.replays.map((r) => h("a", { class: "mono", href: `#/jobs/${r.id}` }, short(r.id, 12), " "))],
  ])));

  const lease = panel("Worker & lease", h("div", { class: "panel-b" }, kv([
    ["Lease owner", j.lease_owner || "none"], ["Lease", j.lease_owner ? (d.lease.live ? pill("ok", "live") : pill("bad", "expired")) : h("span", { class: "mute" }, "not held")], ["Expires", absTime(d.lease.expires_at)],
    ["Fence token", String(d.lease.fence)], ["Last heartbeat", rel(d.lease.last_heartbeat_at)], ["Attempt", `${j.attempt} (${j.failed_attempts} failed) · retry budget ${j.retry_policy.max_attempts}`], ["Retry at", j.retry_at ? absTime(j.retry_at) : "—"]]),
    h("p", { class: "mute" }, "A stale worker is fenced: writes carrying an older fence token are rejected.")));

  const resume = d.resume;
  const cp = panel("Checkpoints & resume", h("div", { class: "stack" }, h("div", { class: "panel-b" }, h("div", { class: "row" }, resume.eligible ? pill("ok", `Resume eligible via ${resume.how}`) : pill("mute", "Not resumable now"), h("span", { class: "mute" }, resume.note))),
    d.checkpoints.length ? table([{ h: "#", f: (c) => c.seq, cls: "num" }, { h: "Stage", f: (c) => c.stage }, { h: "Valid", f: (c) => (c.valid ? pill("ok", "valid") : pill("bad", "invalidated")) }, { h: "Checksum", f: (c) => mono(short(c.checksum, 10)) }, { h: "Base commit", f: (c) => mono(short(c.base_commit, 8)) }, { h: "Note", f: (c) => c.invalidated_reason || "" }], d.checkpoints, { aria: "Checkpoints" }) : empty("No checkpoints yet")));

  const attempts = panel("Attempt history", d.attempts.length ? table([{ h: "#", f: (a) => a.attempt_no, cls: "num" }, { h: "Worker", f: (a) => mono(a.worker_id) }, { h: "Fence", f: (a) => a.fence, cls: "num" }, { h: "Started", f: (a) => absTime(a.started_at) }, { h: "Ended", f: (a) => (a.ended_at ? absTime(a.ended_at) : "running") }, { h: "End state", f: (a) => (a.end_state ? pill(a.end_state) : "—") }], d.attempts, { aria: "Attempts" }) : empty("No attempts recorded"));

  const err = j.error ? panel("Structured error", h("div", { class: "panel-b" }, kv([["Code", mono(j.error.code_final || j.error.code)], ["Kind", j.error.kind || (j.error.transient ? "transient" : "permanent")], ["Message", j.error.message], ["Stage", j.error.stage], ["Recovery", j.error.recovery]]))) : null;

  const risk = panel("Risk assessment & policy", d.risk_assessments.length ? h("div", { class: "panel-b stack" }, d.risk_assessments.slice(0, 1).map((r) => h("div", { class: "stack" },
    kv([["Policy", `${r.policy_name} v${r.policy_version}`], ["Score", String(r.score)], ["Tier", pill(r.tier, r.tier)], ["Repair decision", label(r.repair_decision)]]),
    h("div", { class: "chips" }, (r.reason_codes || []).map((c) => h("span", { class: "chip" }, c)))))) : empty("No risk assessment yet", "Risk is computed after evidence review."));

  const pendAppr = d.approvals.find((a) => a.status === "pending");
  const apprList = panel("Approvals (UNWIND governance)", d.approvals.length ? h("div", { class: "stack" }, d.approvals.map((a) => h("div", { class: "panel-b stack" },
    h("div", { class: "row" }, mono(a.id), pill(a.status), pill("stub", a.provider_label, "t-mute")),
    kv([["Requested", `${a.requested_by} · ${absTime(a.requested_at)}`], ["Expires", absTime(a.expires_at)], a.decided_by && ["Decided", `${a.decided_by} · ${absTime(a.decided_at)}${a.decision_note ? " — " + a.decision_note : ""}`], a.revoked_by && ["Revoked", `${a.revoked_by} — ${a.revoke_reason || ""}`], ["Scope hash", mono(short(a.scope_hash, 16))]]),
    h("details", h("summary", "Scoped grant"), h("pre", { class: "code" }, JSON.stringify(a.scope, null, 2))),
    h("div", { class: "row" }, ["approve", "reject", "revoke"].map((n) => { const x = actions.find((z) => z.action === n); if (!x) return null; const live = (n === "revoke" ? ["pending", "approved"] : ["pending"]).includes(a.status); return btn(label(n), { small: true, kind: n === "approve" ? "primary" : n === "approve" ? "primary" : "danger", disabled: !x.enabled || !live, reason: !live ? `approval is ${a.status}` : x.reason, onclick: () => act(d, n, refresh, { approval: a }) }); }))))) : empty("No approval requested", "Only write-capable repairs request approval; scans never do."), { sub: "dev stub — not production governance" });

  const findings = panel("Findings in this job", d.findings.length ? table([{ h: "Package", f: (f) => h("a", { href: `#/dependencies?finding=${f.id}` }, `${f.package} ${f.installed_version}`) }, { h: "Severity", f: (f) => sevBadge(f.severity) }, { h: "Advisories", f: (f) => f.advisory_ids.join(", ") }, { h: "Fix", f: (f) => f.selected_fix || h("span", { class: "mute" }, "none established") }, { h: "Evidence", f: (f) => pill(f.evidence_status === "ok" ? "ok" : f.evidence_status, label(f.evidence_status)) }], d.findings, { aria: "Findings" }) : empty("No findings recorded for this job"));

  const ev = panel("Evidence references", d.evidence.length ? table([{ h: "Advisory", f: (e) => e.advisory_id }, { h: "Package", f: (e) => e.package }, { h: "Source", f: (e) => `${e.source} (${e.source_mode})` }, { h: "Retrieved", f: (e) => absTime(e.retrieved_at) }, { h: "Hash", f: (e) => mono(short(e.content_hash, 10)) }], d.evidence, { aria: "Evidence" }) : empty("No evidence referenced"));

  const art = panel("Artifacts & verification results", d.artifacts.length ? table([{ h: "Kind", f: (a) => label(a.kind) }, { h: "Name", f: (a) => a.name }, { h: "Size", f: (a) => `${num(a.size)} B`, cls: "num" }, { h: "SHA-256", f: (a) => mono(short(a.sha256, 12)) }, { h: "", f: (a) => btn("View", { small: true, ic: "eye", onclick: () => viewArtifact(j.id, a) }) }], d.artifacts, { aria: "Artifacts" }) : empty("No artifacts", "Patch, test log, verifier report and Repair Proof appear only if a repair actually ran."));

  const notif = panel("Notifications", d.notifications.length ? table([{ h: "Event", f: (n) => n.event_type }, { h: "Channel", f: (n) => n.channel }, { h: "Status", f: (n) => pill(n.status) }, { h: "Attempts", f: (n) => n.attempts, cls: "num" }, { h: "Error", f: (n) => n.last_error || "" }], d.notifications, { aria: "Notifications" }) : empty("No notifications"), { sub: "'local' = outbox record, not external delivery" });

  return h("div", { class: "stack" }, header, h("div", { class: "grid g-main" },
    h("div", { class: "stack" }, timeline, cp, attempts, err, findings, ev, art), h("div", { class: "stack" }, info, lease, risk, apprList, notif)));
}

async function viewArtifact(jobId, a) {
  try {
    const x = await api("GET", `/api/jobs/${jobId}/artifacts/${a.id}`);
    const pre = h("pre", { class: "code diff" }, x.content.split("\n").map((l) => h("div", { class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "" }, l || " ")));
    const dlg = h("dialog", { class: "dlg", style: null, "aria-label": a.name }, h("h2", `${label(a.kind)} · ${a.name}`), h("p", { class: "mono mute" }, "sha256 ", a.sha256), pre, h("div", { class: "dlg-f" }, btn("Close", { onclick: () => dlg.close() })));
    dlg.style.width = "min(900px, 94vw)";
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg); dlg.showModal();
  } catch (e) { toast(e.message, "bad"); }
}
