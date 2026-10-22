// E. Dependency Intelligence — confirmed facts and hypotheses are rendered separately, as the backend separates them.
import { h, api, qs, panel, pill, btn, kv, table, pager, empty, sevBadge, absTime, rel, label, short, select, num, mono, errorBox, loading } from "../lib.js";
import { icon } from "../icons.js";

export default function (ctx) {
  const q = ctx.query;
  const root = h("div", { class: "split" });
  const left = h("div"), right = h("div", { class: "sticky" });
  root.append(left, right);
  const limit = 25, offset = Number(q.offset || 0);
  const search = h("input", { class: "inp", type: "search", value: q.q || "", placeholder: "Package or advisory id", "aria-label": "Search findings", onkeydown: (e) => { if (e.key === "Enter") ctx.setQuery({ q: e.target.value, offset: "" }, false); } });
  const body = h("div");
  left.append(panel("Findings", h("div", h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search", 14), search),
    select([["", "Any severity"], ...["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"].map((s) => [s, s])], q.severity, (v) => ctx.setQuery({ severity: v, offset: "" }), "Severity"),
    select([["", "Any status"], ["open", "Open"], ["resolved", "Resolved"]], q.status, (v) => ctx.setQuery({ status: v, offset: "" }), "Status"),
    select([["", "Any ecosystem"], ["PyPI", "Python (PyPI)"], ["npm", "JavaScript (npm)"]], q.ecosystem, (v) => ctx.setQuery({ ecosystem: v, offset: "" }), "Ecosystem")), body), { sub: "stored findings from real inspections" }));
  ctx.live(body, () => api("GET", "/api/findings" + qs({ repo_id: q.repo_id, severity: q.severity, status: q.status, ecosystem: q.ecosystem, q: q.q, limit, offset })), (d) =>
    d.items.length ? h("div", table([
      { h: "Package", f: (f) => h("a", { href: "#/dependencies" + qs({ ...q, finding: f.id }), onclick: (e) => { e.preventDefault(); ctx.setQuery({ finding: f.id }, false); } }, h("strong", f.package), " ", h("span", { class: "mono" }, f.installed_version)) },
      { h: "Sev", f: (f) => sevBadge(f.severity) }, { h: "Advisories", f: (f) => f.advisory_ids.slice(0, 2).join(", ") + (f.advisory_ids.length > 2 ? "…" : "") },
      { h: "Fix", f: (f) => f.selected_fix || h("span", { class: "mute" }, "none established") }, { h: "Evidence", f: (f) => pill(f.evidence_status === "ok" ? "ok" : f.evidence_status, label(f.evidence_status)) },
      { h: "Rel.", f: (f) => label(f.relationship) },
    ], d.items, { aria: "Findings", rowClass: (f) => (f.id === q.finding ? "attn" : "") }), pager(d, (o) => ctx.setQuery({ offset: o }, false)))
      : empty("No findings", "Findings appear after an inspection finds known-vulnerable dependencies. Run one from Repository Fleet."), { ms: 8000 });
  if (q.finding) ctx.live(right, () => api("GET", `/api/findings/${q.finding}`), (d) => detail(d), { ms: 15000 });
  else right.append(panel("Finding detail", empty("Select a finding", "Facts, hypotheses, evidence sources and the candidate repair plan appear here.")));
  return root;
}

function detail(d) {
  const f = d.finding;
  return h("div", { class: "stack" }, panel(`${f.package} ${f.installed_version}`, h("div", { class: "panel-b stack" },
    h("div", { class: "row" }, sevBadge(f.severity), pill(f.evidence_status === "ok" ? "ok" : f.evidence_status, "evidence " + label(f.evidence_status)), pill(f.status), h("span", { class: "mute" }, f.ecosystem)),
    kv([["Manifests", f.manifest_paths.map((p) => h("span", { class: "chip" }, p))], ["Relationship", label(f.relationship)], ["Affected ranges", f.affected_ranges.join(" · ") || "—"], ["Fix candidates", f.fixed_candidates.join(", ") || "none"], ["Selected fix", f.selected_fix || "none established"], ["Risk score", String(f.risk_score)], ["Reason codes", h("div", { class: "chips" }, f.reason_codes.map((c) => h("span", { class: "chip" }, c)))], ["Last job", f.last_job_id ? h("a", { class: "mono", href: `#/jobs/${f.last_job_id}` }, short(f.last_job_id, 14)) : "—"]]),
    f.limitations.length ? h("div", { class: "note warn" }, h("strong", "Limitations"), h("ul", f.limitations.map((l) => h("li", l)))) : null)),
    panel("Confirmed facts", h("ul", { class: "list" }, d.facts.map((x) => h("li", icon("check", 16), h("div", { class: "main" }, x))))),
    panel("Hypotheses — not verified", d.hypotheses.length ? h("ul", { class: "list" }, d.hypotheses.map((x) => h("li", icon("alert", 16), h("div", { class: "main" }, x)))) : empty("No open hypotheses")),
    panel("Candidate repair plan", d.repair_plan ? h("div", { class: "panel-b stack" }, h("div", { class: "row" }, d.repair_plan.eligible_for_automated_repair ? pill("pending", "eligible to PROPOSE a repair") : pill("blocked", "automated repair blocked"), h("span", { class: "mute" }, `score ${d.repair_plan.score} · tier ${d.repair_plan.tier}`)),
      d.repair_plan.blockers.length ? h("div", { class: "chips" }, d.repair_plan.blockers.map((b) => h("span", { class: "chip" }, b))) : null,
      d.repair_plan.requirements.length ? h("ol", d.repair_plan.requirements.map((r) => h("li", r))) : h("p", { class: "mute" }, "Human review required; no automated path.")) : empty("No plan yet", "A plan exists after a risk assessment ran for this finding.")),
    panel("Advisory evidence", d.evidence.length ? h("ul", { class: "list" }, d.evidence.map((e) => h("li", h("div", { class: "main" }, h("div", { class: "row" }, h("strong", e.advisory_id), pill(e.source_mode, e.source_mode, "t-mute"), h("span", { class: "mute" }, e.source)),
      h("div", { class: "m" }, `retrieved ${absTime(e.retrieved_at)} · hash ${short(e.content_hash, 10)}`), e.url && h("div", { class: "m mono" }, e.url), h("div", { class: "m" }, typeof e.summary === "object" ? (e.summary.summary || e.summary.details || "") : "")))) ) : empty("No evidence")),
    panel("Observation history", d.observations.length ? table([{ h: "When", f: (o) => absTime(o.observed_at) }, { h: "Version", f: (o) => o.installed_version }, { h: "Severity", f: (o) => sevBadge(o.severity) }, { h: "Risk", f: (o) => o.risk_score }, { h: "Job", f: (o) => h("a", { class: "mono", href: `#/jobs/${o.job_id}` }, short(o.job_id, 12)) }], d.observations, { aria: "Observations" }) : empty("No observations")));
}
