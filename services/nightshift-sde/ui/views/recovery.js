// F. Recovery & Reliability Center — recommendations come from deterministic rules; actions go through the same guarded API.
import { h, api, panel, pill, btn, table, empty, toast, confirmDialog, absTime, rel, label, short, session, mono, kv } from "../lib.js";

const can = (p) => (session.me?.permissions || []).includes(p);

async function jobAct(j, action, rf) {
  const danger = action === "replay";
  const r = await confirmDialog({ title: `${label(action)} ${short(j.id, 14)}?`, body: { retry: "Skips remaining backoff; budget and approval gates still apply.", replay: "Creates a NEW linked job; the original history is preserved. Replay can never bypass approval." }[action] || "Proceed?", confirm: label(action), danger });
  if (!r) return;
  try { await api("POST", `/api/jobs/${j.id}/${action}`, {}); toast(`${label(action)} applied`); rf(); } catch (e) { toast(`${e.message}${e.corr ? " (" + e.corr + ")" : ""}`, "bad"); }
}
const jobTable = (rows, rf, extra = []) => table([
  { h: "Job", f: (j) => h("a", { class: "mono", href: `#/jobs/${j.id}` }, short(j.id, 14)) }, { h: "State", f: (j) => pill(j.state) }, { h: "Error", f: (j) => (j.error_code ? mono(j.error_code) : "—") },
  { h: "Progress", f: (j) => rel(j.last_progress_at) }, { h: "Recommendation", f: (j) => j.recommendation },
  { h: "Eligibility", f: (j) => (j.resume.eligible ? pill("ok", `via ${j.resume.how}`) : pill("mute", "no")) },
  { h: "Action", f: (j) => h("div", { class: "row" }, ...extra.map((a) => btn(label(a), { small: true, disabled: !can("operate"), reason: "requires operator", onclick: () => jobAct(j, a, rf) }))) },
], rows, { aria: "Jobs" });

export default function (ctx) {
  const root = h("div");
  ctx.live(root, () => api("GET", "/api/recovery"), (d, rf) => {
    const sec = (title, rows, node, sub) => panel(title, rows.length ? node : empty("None right now"), { sub: sub || `${rows.length} item(s)` });
    return h("div", { class: "stack" },
      h("div", { class: "note" }, "The watchdog never bypasses a gate to make a job green: automatic recovery only reclaims leases, retries or resumes when idempotency, checkpoints and approval validity allow it. Generated ", absTime(d.generated_at), "."),
      sec("Watchdog alerts", d.alerts, table([{ h: "Sev", f: (a) => pill(a.severity) }, { h: "Condition", f: (a) => h("div", h("strong", label(a.kind)), h("div", { class: "mute" }, a.condition)) }, { h: "Subject", f: (a) => mono(a.subject_type + " " + short(a.subject_id, 14)) }, { h: "Last progress", f: (a) => a.last_progress || "—" }, { h: "Recommended", f: (a) => a.recommended_action }, { h: "Auto-recovery", f: (a) => (a.auto_recovery_attempted ? `attempted: ${a.recovery_result || "?"}` : "not attempted") }, { h: "Status", f: (a) => pill(a.status === "open" ? "pending" : "ok", a.status) }, { h: "Detected", f: (a) => rel(a.detected_at) }, { h: "Corr.", f: (a) => mono(short(a.correlation_id, 10)) }], d.alerts, { aria: "Alerts" })),
      h("div", { class: "grid g2" },
        sec("Stuck jobs", d.stuck_jobs, jobTable(d.stuck_jobs, rf), "lease expired or no progress"),
        sec("Expired leases", d.expired_leases, jobTable(d.expired_leases, rf), "reclaimed automatically by the watchdog")),
      sec("Retry queue", d.retry_queue, table([{ h: "Job", f: (j) => h("a", { class: "mono", href: `#/jobs/${j.id}` }, short(j.id, 14)) }, { h: "Error", f: (j) => mono(j.error_code || "—") }, { h: "Retry at", f: (j) => `${absTime(j.retry_at)} (${rel(j.retry_at)})` }, { h: "Failed attempts", f: (j) => j.failed_attempts, cls: "num" }, { h: "Why", f: (j) => j.recommendation }, { h: "Action", f: (j) => btn("Retry now", { small: true, ic: "refresh", disabled: !can("operate"), reason: "requires operator", onclick: () => jobAct(j, "retry", rf) }) }], d.retry_queue, { aria: "Retry queue" }), "exponential backoff with jitter"),
      sec("Dead-letter & failed jobs", d.dead_letter, jobTable(d.dead_letter, rf, ["replay"]), "replay creates a new linked job"),
      sec("Failed or missed schedules", d.failed_schedules, table([{ h: "Schedule", f: (s) => s.name }, { h: "Repository", f: (s) => s.repo_name }, { h: "Status", f: (s) => pill(s.status) }, { h: "Last result", f: (s) => (s.last_status ? pill(s.last_status) : "—") }, { h: "Next run", f: (s) => absTime(s.next_run_at) }], d.failed_schedules, { aria: "Schedules" })),
      sec("Provider outages", d.provider_outages, table([{ h: "Provider", f: (p) => p.label }, { h: "Status", f: (p) => pill(p.status) }, { h: "Consecutive failures", f: (p) => p.consecutive_failures, cls: "num" }, { h: "Last error", f: (p) => p.last_error_code || "—" }], d.provider_outages, { aria: "Providers" })),
      sec("Expired approvals", d.expired_approvals, table([{ h: "Approval", f: (a) => mono(short(a.id, 12)) }, { h: "Job", f: (a) => h("a", { class: "mono", href: `#/jobs/${a.job_id}` }, short(a.job_id, 12)) }, { h: "Expired", f: (a) => absTime(a.expires_at) }, { h: "Job state", f: (a) => pill(a.job_state) }], d.expired_approvals, { aria: "Expired approvals" }), "a replay + fresh approval is required"),
      sec("Recovery history", d.history, table([{ h: "When", f: (x) => absTime(x.created_at) }, { h: "Kind", f: (x) => label(x.kind) }, { h: "By", f: (x) => `${x.actor} (${x.source})` }, { h: "Job", f: (x) => x.job_id ? h("a", { class: "mono", href: `#/jobs/${x.job_id}` }, short(x.job_id, 12)) : "—" }, { h: "Result", f: (x) => pill(x.result) }, { h: "Corr.", f: (x) => mono(short(x.correlation_id, 10)) }], d.history, { aria: "Recovery history" }), "append-only"));
  }, { ms: 5000 });
  return root;
}
