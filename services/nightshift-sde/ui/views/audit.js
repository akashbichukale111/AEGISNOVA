// G. Evidence & Audit Explorer — append-only events with hash-chain verification, plus governance/provider/notification views.
import { h, api, qs, panel, pill, btn, table, pager, empty, absTime, rel, label, short, mono, select, toast } from "../lib.js";
import { icon } from "../icons.js";

const TABS = [["events", "Event history"], ["approvals", "Approvals & revocations"], ["policy", "Policy decisions"], ["proofs", "Repair proofs"], ["providers", "Provider usage"], ["notifications", "Notifications"], ["model", "Model usage"]];

export default function (ctx) {
  const q = ctx.query, tab = q.tab || "events";
  const root = h("div", { class: "stack" });
  const tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Audit views" }, TABS.map(([k, t]) => h("button", { role: "tab", "aria-selected": String(k === tab), onclick: () => ctx.setQuery({ tab: k, offset: "" }, false) }, t)));
  const body = h("div");
  root.append(panel(null, h("div", tabs)), body);
  if (tab === "events") events(ctx, body); else extras(ctx, body, tab);
  return root;
}

function events(ctx, body) {
  const q = ctx.query, limit = 50, offset = Number(q.offset || 0);
  const inp = (k, ph, w) => h("input", { class: "inp", value: q[k] || "", placeholder: ph, "aria-label": ph, style: null, onkeydown: (e) => { if (e.key === "Enter") ctx.setQuery({ [k]: e.target.value, offset: "" }, false); }, onblur: (e) => { if ((q[k] || "") !== e.target.value) ctx.setQuery({ [k]: e.target.value, offset: "" }, false); } });
  const tb = h("div", { class: "toolbar" }, inp("job_id", "Job id"), inp("repo_id", "Repository id"), inp("type", "Event type prefix (e.g. job.)"), inp("actor", "Actor"),
    select([["", "Any job state"], ...["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "DEAD_LETTER", "WAITING_FOR_APPROVAL", "RETRY_WAIT", "PAUSED", "CANCELLED", "EXPIRED"].map((s) => [s, label(s)])], q.state, (v) => ctx.setQuery({ state: v, offset: "" }), "Job state"),
    h("label", { class: "mute" }, "Since ", h("input", { class: "inp", type: "datetime-local", value: q.since_local || "", onchange: (e) => ctx.setQuery({ since_local: e.target.value, since: e.target.value ? new Date(e.target.value).toISOString() : "", offset: "" }) })),
    btn("Clear", { small: true, onclick: () => ctx.setQuery({ job_id: "", repo_id: "", type: "", actor: "", state: "", since: "", since_local: "", offset: "" }, false) }));
  const inner = h("div");
  const pg = panel("Event history", h("div", tb, inner), { sub: "append-only, hash-chained" });
  body.append(pg);
  ctx.live(inner, () => api("GET", "/api/audit" + qs({ job_id: q.job_id, repo_id: q.repo_id, type: q.type, actor: q.actor, state: q.state, since: q.since, limit, offset })), (d) => h("div",
    h("div", { class: "panel-b" }, d.chain.ok ? pill("ok", `Hash chain verified (${d.chain.checked ?? d.total} events)`) : pill("bad", `Hash chain BROKEN at event ${d.chain.broken_at_event ?? "?"}`), h("span", { class: "mute" }, " Tamper-evident only: this is not cryptographic immutability or external attestation.")),
    d.items.length ? table([{ h: "#", f: (e) => e.id, cls: "num mono" }, { h: "Time", f: (e) => h("span", { title: e.ts }, absTime(e.ts)) }, { h: "Type", f: (e) => mono(e.type) }, { h: "Actor", f: (e) => e.actor }, { h: "Job", f: (e) => e.job_id ? h("a", { class: "mono", href: `#/jobs/${e.job_id}` }, short(e.job_id, 12)) : "—" }, { h: "Corr.", f: (e) => mono(short(e.correlation_id, 10)) },
      { h: "Data", f: (e) => h("details", h("summary", Object.keys(e.data || {}).slice(0, 3).join(", ") || "—"), h("pre", { class: "code" }, JSON.stringify(e.data, null, 2))) }], d.items, { aria: "Events" }) : empty("No events match"), pager(d, (o) => ctx.setQuery({ offset: o }, false))), { ms: 6000 });
}

function extras(ctx, body, tab) {
  const inner = h("div");
  body.append(inner);
  ctx.live(inner, () => api("GET", "/api/audit/extras"), (x) => {
    const cfg = {
      approvals: ["Approvals, decisions & revocations", x.approvals, [{ h: "Approval", f: (a) => mono(short(a.id, 12)) }, { h: "Job", f: (a) => h("a", { class: "mono", href: `#/jobs/${a.job_id}` }, short(a.job_id, 12)) }, { h: "Status", f: (a) => pill(a.status) }, { h: "Requested", f: (a) => `${a.requested_by} · ${absTime(a.requested_at)}` }, { h: "Decision", f: (a) => (a.decided_by ? `${a.decided_by} · ${absTime(a.decided_at)}` : "—") }, { h: "Revocation", f: (a) => (a.revoked_by ? `${a.revoked_by}: ${a.revoke_reason || ""}` : "—") }, { h: "Scope hash", f: (a) => mono(short(a.scope_hash, 12)) }], "dev-stub governance (not UNWIND)"],
      policy: ["Policy decisions", x.policy_decisions, [{ h: "When", f: (p) => absTime(p.created_at) }, { h: "Job", f: (p) => h("a", { class: "mono", href: `#/jobs/${p.job_id}` }, short(p.job_id, 12)) }, { h: "Policy", f: (p) => `${p.policy_name} v${p.policy_version}` }, { h: "Score", f: (p) => p.score, cls: "num" }, { h: "Tier", f: (p) => p.tier }, { h: "Decision", f: (p) => pill(p.repair_decision === "propose" ? "pending" : "blocked", label(p.repair_decision)) }], "deterministic"],
      proofs: ["Repair Proof references", x.repair_proofs, [{ h: "When", f: (p) => absTime(p.created_at) }, { h: "Job", f: (p) => h("a", { class: "mono", href: `#/jobs/${p.job_id}` }, short(p.job_id, 12)) }, { h: "Name", f: (p) => p.name }, { h: "SHA-256", f: (p) => mono(short(p.sha256, 16)) }], "exist only for verified repairs"],
      providers: ["Provider usage", x.provider_usage, [{ h: "When", f: (p) => absTime(p.at) }, { h: "Provider", f: (p) => p.provider }, { h: "Operation", f: (p) => p.operation }, { h: "Result", f: (p) => pill(p.ok ? "ok" : "failed", p.ok ? "ok" : p.error_code || "error") }, { h: "Latency", f: (p) => `${p.latency_ms} ms`, cls: "num" }], "measured calls"],
      notifications: ["Notification delivery", x.notifications, [{ h: "When", f: (n) => absTime(n.created_at) }, { h: "Event", f: (n) => n.event_type }, { h: "Job", f: (n) => n.job_id ? h("a", { class: "mono", href: `#/jobs/${n.job_id}` }, short(n.job_id, 12)) : "—" }, { h: "Channel", f: (n) => n.channel }, { h: "Status", f: (n) => pill(n.status) }, { h: "Attempts", f: (n) => n.attempts, cls: "num" }, { h: "Error", f: (n) => n.last_error || "" }], "'local' is an outbox record, not external delivery"],
    }[tab];
    if (tab === "model") return panel("Model / provider usage", h("div", { class: "panel-b" }, h("div", { class: "note" }, x.model_usage.detail), h("p", { class: "mute" }, "Status: ", x.model_usage.status)));
    return panel(cfg[0], cfg[1].length ? table(cfg[2], cfg[1], { aria: cfg[0] }) : empty("No records yet", "Nothing is fabricated: rows appear only when the real activity occurs."), { sub: cfg[3] });
  }, { ms: 8000 });
}
