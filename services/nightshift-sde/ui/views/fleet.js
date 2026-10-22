// D. Repository Fleet — health from stored state; 'connected' only from a real check.
import { h, api, panel, pill, btn, kv, empty, toast, confirmDialog, sevBadge, absTime, rel, label, short, session, uuid, num, errorBox } from "../lib.js";

const can = (p) => (session.me?.permissions || []).includes(p);
const SEV = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];

export default function (ctx) {
  const root = h("div");
  ctx.live(root, () => api("GET", "/api/fleet"), (d, rf) => d.items.length ? h("div", { class: "grid g2" }, d.items.map((r) => card(r, rf))) :
    panel("Repository Fleet", empty("No repositories registered", h("span", {}, "Seed synthetic demo repositories with ", h("code", "python -m nightshift seed-demo"), " or register one via ", h("code", "POST /api/repos"), " (admin)."))), { ms: 6000 });
  return root;
}

function card(r, rf) {
  const sev = r.open_findings_by_severity;
  const integ = r.integration;
  const trigger = async (repair) => {
    const c = await confirmDialog({ title: `${repair ? "Trigger write-capable run" : "Trigger read-only inspection"} on ${r.name}?`, confirm: "Trigger", body: repair ? "This permits the job to PROPOSE a repair. Nothing is written without a scoped approval, passing regression tests and independent verification." : "A read-only inspection. It never writes code." });
    if (!c) return;
    try {
      const res = await api("POST", `/api/repos/${r.id}/trigger`, { allow_repair: repair }, { idempotencyKey: "ui-" + uuid() });
      toast(res.created ? "Job created" : res.note); location.hash = `#/jobs/${res.job.id}`;
    } catch (e) { toast(`${e.message}${e.corr ? " (" + e.corr + ")" : ""}`, "bad"); }
  };
  const check = async () => { try { const x = await api("POST", `/api/repos/${r.id}/check`); toast(x.status === "ok" ? "Repository check passed: " + x.detail : "Repository check failed: " + x.detail, x.status === "ok" ? "good" : "bad"); rf(); } catch (e) { toast(e.message, "bad"); } };
  return panel(null, h("div", { class: "panel-b stack" },
    h("div", { class: "row" }, h("h2", r.name), r.is_demo && pill("stub", "synthetic demo", "t-mute"), r.allow_repair ? pill("pending", "repair-capable") : pill("ok", "read-only"), h("span", { class: "grow" }), pill(integ.status === "ok" ? "ok" : "failed", integ.status === "ok" ? "Local path verified" : "Path check failed")),
    h("div", { class: "mono mute" }, r.slug),
    h("div", { class: "row" }, SEV.filter((s) => sev[s]).map((s) => h("span", { class: "row" }, sevBadge(s), h("b", num(sev[s])))), !r.open_findings && h("span", { class: "mute" }, r.last_successful_scan ? "No open findings" : "Not scanned yet")),
    kv([["Default branch", r.default_branch], ["Latest snapshot", r.latest_snapshot ? `${short(r.latest_snapshot.commit_sha || r.latest_snapshot.tree_hash, 10)} · ${r.latest_snapshot.file_count} files · ${rel(r.latest_snapshot.taken_at)}` : "none"],
      ["Last successful scan", r.last_successful_scan ? h("a", { href: `#/jobs/${r.last_successful_scan.id}` }, `${rel(r.last_successful_scan.finished_at)} (${label(r.last_successful_scan.outcome)})`) : "never"],
      ["Open jobs", h("a", { href: `#/jobs?repo_id=${r.id}` }, String(r.open_jobs))], ["Failures (7d)", String(r.recent_failures_7d)],
      ["Risk trend", r.risk_trend ? r.risk_trend.map((t) => t.max_risk).join(" → ") : h("span", { class: "mute" }, r.risk_trend_note)],
      ["Policy", `${r.policy.name} v${r.policy.version}`], ["Test command", r.test_command_key], ["Max concurrency", String(r.max_concurrent_jobs)],
      ["GitHub", pill("mute", "not connected")],
      ["Schedules", r.schedules.length ? r.schedules.map((s) => h("div", {}, s.name, " ", pill(s.status), h("span", { class: "mute" }, s.next_run_at ? ` next ${absTime(s.next_run_at)}` : ""))) : h("span", { class: "mute" }, "none")]]),
    h("div", { class: "row" }, btn("Run inspection", { kind: "primary", ic: "play", disabled: !can("operate"), reason: "requires operator", onclick: () => trigger(false) }),
      btn("Run with repair allowed", { ic: "lock", disabled: !can("authorize_repair") || !r.allow_repair, reason: !r.allow_repair ? "repository is not repair-capable" : "requires approver/admin", onclick: () => trigger(true) }),
      btn("Check path", { ic: "check", disabled: !can("operate"), reason: "requires operator", onclick: check }),
      btn("Findings", { ic: "shield", onclick: () => (location.hash = `#/dependencies?repo_id=${r.id}`) }))));
}
