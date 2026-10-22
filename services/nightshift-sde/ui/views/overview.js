// A. Command Center — every number comes from GET /api/overview (real backend state).
import { h, api, panel, pill, sevBadge, empty, dur, rel, absTime, num, label, tone, table, short } from "../lib.js";
import { icon } from "../icons.js";

const STAGES = ["QUEUED", "VALIDATING", "SNAPSHOTTING", "INSPECTING", "RESEARCHING", "EVIDENCE_REVIEW", "RISK_ASSESSMENT", "WAITING_FOR_APPROVAL", "READY_TO_EXECUTE", "EXECUTING", "TESTING", "INDEPENDENT_VERIFICATION", "RETRY_WAIT"];
const SEV = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];
const ORDER = ["QUEUED", "VALIDATING", "SNAPSHOTTING", "INSPECTING", "RESEARCHING", "EVIDENCE_REVIEW", "RISK_ASSESSMENT", "WAITING_FOR_APPROVAL", "READY_TO_EXECUTE", "EXECUTING", "TESTING", "INDEPENDENT_VERIFICATION"];

function kpi(href, v, l, s, cls = "ok") { return h("a", { class: `kpi ${cls}`, href }, h("div", { class: "v" }, v), h("div", { class: "l" }, l), s && h("div", { class: "s" }, s)); }

export function miniTrack(state) {
  const idx = ORDER.indexOf(state);
  return h("div", { class: "track", role: "img", "aria-label": `Pipeline position: ${label(state)}` }, ORDER.slice(1).map((s, i) => h("i", { class: "seg " + (idx > i + 1 ? "done" : idx === i + 1 ? "now" : ""), title: label(s) })));
}

export default function (ctx) {
  const root = h("div", { class: "stack" });
  ctx.live(root, () => api("GET", "/api/overview"), (o) => {
    const mode = o.mode;
    const degraded = mode.status === "degraded";
    const banner = h("div", { class: "mode" + (degraded ? " degraded" : "") },
      h("span", { class: "big" }, icon("bolt", 16), " ", mode.label), pill(degraded ? "degraded" : "ok", degraded ? "Degraded — see attention list" : "Operational"),
      h("span", { class: "sep" }), h("span", { class: "mute" }, "AWS orchestration: "), pill("mute", "Not configured"), h("span", { class: "mute" }, mode.aws.detail),
      h("span", { class: "grow" }), h("span", { class: "mute" }, `Server time ${absTime(o.generated_at)}`));

    const kpis = h("div", { class: "kpis" },
      kpi("#/jobs", num(o.active_jobs.length), "Active jobs", `${num(o.jobs_total)} total recorded`),
      kpi("#/jobs?state=QUEUED", num(o.queue.depth), "Queued", o.queue.depth ? `oldest ${dur(o.queue.oldest_age_seconds)}` : "queue empty", o.queue.oldest_age_seconds > 600 ? "warn" : "ok"),
      kpi("#/jobs?state=RETRY_WAIT", num(o.queue.retry_wait), "In retry backoff", "bounded, observable", o.queue.retry_wait ? "warn" : "ok"),
      kpi("#/recovery", num(o.dead_letter), "Dead-letter", o.dead_letter ? "operator attention" : "none", o.dead_letter ? "hot" : "ok"),
      kpi("#/jobs?state=WAITING_FOR_APPROVAL", num(o.approvals.pending), "Approvals pending", `${num(o.approvals.expired)} expired`, o.approvals.pending ? "warn" : "ok"),
      kpi("#/recovery", num(o.alerts.length), "Open alerts", "watchdog", o.alerts.length ? "hot" : "ok"),
      kpi("#/audit?type=recovery", num(o.recovery_24h), "Recoveries (24h)", "leases/retries/replays"),
      kpi("#/fleet", num(o.fleet_size), "Repositories", "registered"));

    const counts = o.counts_by_state;
    const pipeline = panel("Workflow pipeline", h("div", { class: "pipe" }, STAGES.map((s) => h("a", { class: "st " + (counts[s] ? "on" : "zero"), href: `#/jobs?state=${s}`, style: null, title: `${label(s)}: ${counts[s] || 0} job(s)` }, h("div", { class: "n" }, counts[s] || 0), h("div", { class: "nm" }, label(s))))),
      { sub: "jobs currently in each stage" });

    const active = panel("Active jobs", o.active_jobs.length ? h("ul", { class: "list" }, o.active_jobs.map((j) => h("li", h("div", { class: "main" },
      h("div", { class: "row" }, h("a", { class: "t mono", href: `#/jobs/${j.id}` }, short(j.id, 14)), pill(j.state), j.allow_repair && pill("pending", "write-capable"), pill(j.trigger_type, j.trigger_type, "t-mute")),
      miniTrack(j.state), h("div", { class: "m" }, `attempt ${j.attempt} · last progress ${rel(j.last_progress_at)}${j.last_progress_note ? " · " + j.last_progress_note : ""}`),
      j.lease_expires_at && j.lease_expires_at < o.generated_at && pill("bad", "lease expired"))))) : empty("No jobs are running", "Trigger an inspection from Repository Fleet, or wait for a schedule."), { sub: "from the durable queue" });

    const waiting = o.waiting_jobs.length ? panel("Waiting / needs attention", h("ul", { class: "list" }, o.waiting_jobs.map((j) => h("li", h("div", { class: "main" },
      h("div", { class: "row" }, h("a", { class: "t mono", href: `#/jobs/${j.id}` }, short(j.id, 14)), pill(j.state)),
      h("div", { class: "m" }, j.state === "WAITING_FOR_APPROVAL" ? "Waiting for a human decision — expected, not stalled." : j.state === "RETRY_WAIT" ? `Retry ${rel(j.retry_at)} (attempt ${j.failed_attempts} failed)` : "Paused by an operator."))))), { sub: "approval · retry · paused" }) : null;

    const sevCounts = o.findings_by_severity; const sevTotal = SEV.reduce((a, s) => a + (sevCounts[s] || 0), 0);
    const risk = panel("Dependency risk", sevTotal ? h("div", { class: "panel-b" }, h("div", { class: "bar", role: "img", "aria-label": "Open findings by severity: " + SEV.map((s) => `${s} ${sevCounts[s] || 0}`).join(", ") },
      SEV.filter((s) => sevCounts[s]).map((s) => h("i", { class: "s-" + s.toLowerCase(), style: null, ref: null, dataset: { w: sevCounts[s] }, title: `${s}: ${sevCounts[s]}` }))),
      h("div", { class: "legend" }, SEV.map((s) => h("span", sevBadge(s), " ", h("b", num(sevCounts[s] || 0)))))) : h("div", { class: "panel-b" }, empty("No open findings", "Findings are stored only after an inspection has run.")),
      { sub: `${sevTotal} open finding(s)` });
    // widths via CSSOM (CSP-safe): proportional segments
    queueMicrotask(() => root.querySelectorAll(".bar > i[data-w]").forEach((i) => { i.style.flex = `${i.dataset.w} 1 0`; }));

    const workers = panel("Workers & leases", o.workers.length ? h("ul", { class: "list" }, o.workers.map((w) => h("li", h("div", { class: "main" },
      h("div", { class: "row" }, h("span", { class: "hb" + (w.healthy ? " pulse" : " bad"), "aria-hidden": "true" }), h("span", { class: "mono" }, w.id), pill(w.healthy ? "healthy" : "unavailable", w.healthy ? "heartbeat OK" : "heartbeat lost")),
      h("div", { class: "m" }, `last heartbeat ${w.heartbeat_age_seconds}s ago${w.current_job_id ? " · job " + short(w.current_job_id, 12) : " · idle"}`))))) : empty("No worker has reported", "Start the server (python -m nightshift serve) — the local worker registers on its first heartbeat."));

    const prov = panel("Provider health", h("ul", { class: "list" }, o.providers.map((p) => h("li", h("div", { class: "main" },
      h("div", { class: "row" }, h("span", { class: "t" }, p.label), pill(p.status), pill(p.mode, p.mode, "t-mute")),
      h("div", { class: "m" }, p.last_success_at ? `last success ${rel(p.last_success_at)}` : "no verified successful call yet"))))), { sub: "no 'connected' without a real check" });

    const fresh = panel("Evidence freshness", o.evidence_freshness.length ? table([{ h: "Repository", f: (r) => short(r.repo_id, 12), cls: "mono" }, { h: "Oldest evidence", f: (r) => rel(r.oldest) }, { h: "Newest", f: (r) => rel(r.newest) }], o.evidence_freshness, { aria: "Evidence freshness" })
      : empty("No evidence retrieved yet"));

    const sched = panel("Upcoming scheduled runs", o.upcoming_schedules.length ? table([{ h: "Schedule", f: (s) => h("a", { href: "#/schedules" }, s.name) }, { h: "Next run", f: (s) => h("span", { title: s.next_run_at }, `${absTime(s.next_run_at, s.timezone)} (${s.timezone})`) }, { h: "In", f: (s) => rel(s.next_run_at) }, { h: "Mode", f: (s) => s.allow_repair ? pill("pending", "write-capable") : pill("ok", "read-only") }], o.upcoming_schedules, { aria: "Upcoming schedules" })
      : empty("No active schedules", "Create one in Schedule Studio."), { actions: h("a", { href: "#/schedules" }, "Open Schedule Studio") });

    const recent = panel("Recent outcomes", o.recent_jobs.length ? table([{ h: "Job", f: (j) => h("a", { class: "mono", href: `#/jobs/${j.id}` }, short(j.id, 14)) }, { h: "State", f: (j) => pill(j.state) }, { h: "Outcome", f: (j) => pill(j.outcome, label(j.outcome)) }, { h: "Finished", f: (j) => rel(j.finished_at) }], o.recent_jobs, { aria: "Recent jobs" })
      : empty("No finished jobs yet"));

    const alerts = o.alerts.length ? panel("Watchdog alerts", h("ul", { class: "list" }, o.alerts.map((a) => h("li", h("div", { class: "main" },
      h("div", { class: "row" }, pill(a.severity), h("span", { class: "t" }, label(a.kind)), h("span", { class: "mute mono" }, a.subject_type + " " + short(a.subject_id, 14))),
      h("div", { class: "m" }, a.condition), h("div", { class: "m" }, "Recommended: ", a.recommended_action))))), { sub: "deterministic detections", actions: h("a", { href: "#/recovery" }, "Recovery center") }) : null;

    const tl = panel("Activity timeline", o.timeline.length ? h("ul", { class: "tl" }, o.timeline.slice(0, 14).map((e) => h("li", { class: "t-" + (/fail|dead|expire|revok|reject|alert/.test(e.type) ? "bad" : /complet|approved|verified|recovered/.test(e.type) ? "good" : "") },
      h("div", h("span", { class: "mono" }, e.type), " ", e.job_id && h("a", { class: "mono", href: `#/jobs/${e.job_id}` }, short(e.job_id, 12))),
      h("div", { class: "m mute" }, `${rel(e.ts)} · ${e.actor}`)))) : empty("No events yet", "Events are appended by real activity only."), { actions: h("a", { href: "#/audit" }, "Audit explorer") });

    return h("div", { class: "stack" }, banner, kpis, pipeline,
      h("div", { class: "grid g-main" }, h("div", { class: "stack" }, active, waiting, alerts, sched, recent), h("div", { class: "stack" }, risk, workers, prov, fresh, tl)));
  }, { ms: 4000 });
  return root;
}
