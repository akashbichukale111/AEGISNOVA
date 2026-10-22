const $ = s => document.querySelector(s);
const h = (t, txt, c) => { const e = document.createElement(t); if (txt !== undefined) e.textContent = txt; if (c) e.className = c; return e; };
let cur = null;
async function api(p, o) { const r = await fetch(p, o); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error((j.errors || [j.error || "HTTP " + r.status]).join("; ")); return j; }
const cls = s => /OK|HEALTHY|FRESH|CORROBORATED|CONSISTENT|UNCHANGED|EMPTY/.test(s) && !/UN|NOT/.test(s.replace("UNCHANGED", "")) ? "ok" : /FAIL|ERROR|CONFLICT|UNAVAILABLE|EXPIRED|NOT_CONFIGURED|TIMEOUT|MATERIAL/.test(s) ? "err" : "warn";
const stat = s => h("span", s, cls(String(s)));
function kv(parent, k, v) { const d = h("div", undefined, "card"); d.append(h("div", k, "k")); const x = h("div", undefined, "v"); typeof v === "string" ? x.textContent = v : x.append(v); d.append(x); parent.append(d); }
function table(head, rows) { const w = h("div", undefined, "scroll"), t = h("table"), tr = h("tr"); head.forEach(x => tr.append(h("th", x))); t.append(tr); rows.forEach(r => { const q = h("tr"); r.forEach(c => { const td = h("td"); c instanceof Node ? td.append(c) : td.textContent = c ?? "—"; q.append(td); }); t.append(q); }); w.append(t); return w; }
document.querySelectorAll("nav button").forEach(b => b.onclick = () => { document.querySelectorAll("nav button,.tab").forEach(e => e.classList.remove("on")); b.classList.add("on"); $("#" + b.dataset.t).classList.add("on"); if (b.dataset.t === "prov") loadProv(); if (b.dataset.t === "set") loadSet(); });
function msg(t, c) { const m = $("#msg"); m.textContent = t; m.className = "note " + (c || ""); }
async function go(fn, label) { msg(label + "…"); document.querySelectorAll("button").forEach(b => b.disabled = true); try { render(await fn()); msg("Done.", "ok"); } catch (e) { msg("Error: " + e.message, "err"); } finally { document.querySelectorAll("button").forEach(b => b.disabled = false); $("#refresh").disabled = !cur; } }
$("#f").onsubmit = e => { e.preventDefault(); const body = { sources: ["tavily", "osv", "ghsa"].filter(s => $("#s_" + s).checked) };
  if ($("#pkg").value.trim()) { body.ecosystem = $("#eco").value; body.package = $("#pkg").value.trim(); body.version = $("#ver").value.trim(); }
  if ($("#adv").value.trim()) body.advisory_id = $("#adv").value.trim();
  go(() => api("/api/v1/research", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), "Researching"); };
$("#refresh").onclick = () => go(() => api(`/api/v1/research/${cur}/refresh`, { method: "POST" }), "Refreshing");
function render(b) {
  cur = b.research_id; const ex = $("#export"); ex.href = `/api/v1/research/${cur}/export`; ex.hidden = false; ex.setAttribute("download", "evidence-export.json");
  const m = $("#mode"); m.textContent = b.demo ? "DEMO FIXTURES — not live research" : "LIVE"; m.className = "pill" + (b.demo ? " demo" : "");
  const r = $("#res"); r.replaceChildren();
  if (b.demo) r.append(h("div", "DEMO: this bundle comes from fictional fixtures.", "card warn"));
  const g = h("div", undefined, "grid"); kv(g, "Reconciliation", stat(b.reconciliation.overall)); kv(g, "Freshness", stat(b.freshness.overall));
  kv(g, "Evidence-quality indicator (not a probability)", String(b.quality.indicator) + " / 100"); kv(g, "Snapshot #", String(b.snapshot_seq)); r.append(g);
  const na = h("div", undefined, "card"); na.append(h("div", "Recommended next action", "k"), h("div", b.recommended_next_action)); r.append(na);
  const pc = h("div", undefined, "card"); pc.append(h("div", "Provider status", "k"), table(["Provider", "Status", "Detail", "Records", "Last success"], Object.entries(b.providers).map(([n, p]) => [n, stat(p.status), p.detail, p.record_count + (p.carried_over ? " (prior carried over)" : ""), p.last_success_at]))); r.append(pc);
  const cc = h("div", undefined, "card"); cc.append(h("div", "Citations & sources", "k"));
  if (!b.records.length) cc.append(h("div", "No records returned. This does NOT mean the package is safe.", "warn"));
  b.records.forEach(x => { const d = h("div"); d.append(h("h4", `[${x.citation}] ${x.title}`));
    const l = h("a", x.url, ""); l.href = /^https?:/.test(x.url) ? x.url : "#"; l.rel = "noopener noreferrer"; l.target = "_blank"; d.append(l);
    d.append(table(["Kind", "Provider", "Publisher", "IDs", "Package", "Fixed", "Severity"], [[x.kind === "discovery" ? "discovery (unverified)" : "advisory", x.provider, x.publisher, x.ids.join(", "), x.package ? x.package.name : "", x.fixed_versions.join(", "), x.severity]]));
    d.append(table(["Retrieved", "Published", "Updated", "Freshness", "Hash"], [[x.retrieved_at, x.published, x.modified, b.freshness.per_record[x.citation], x.content_hash.slice(0, 16)]]));
    if (x.snippet) d.append(h("div", "Untrusted snippet: " + x.snippet, "snip")); if (x.provider_score != null) d.append(h("div", "Provider relevance score " + x.provider_score + " (relevance only, not truth)", "note"));
    cc.append(d); }); r.append(cc);
  const lc = h("div", undefined, "card"); lc.append(h("div", "Limitations", "k")); b.limitations.forEach(x => lc.append(h("div", "• " + x))); r.append(lc);
  const cf = $("#cfv"); cf.replaceChildren();
  b.reconciliation.groups.forEach(gp => { const c = h("div", undefined, "card"); c.append(h("h4", gp.group_id + " — "), stat(gp.state)); c.append(h("div", gp.rationale));
    c.append(h("div", "Citations: " + gp.citations.join(", ") + " · independent origins: " + (gp.independent_origins.join(", ") || "none"), "note"));
    gp.conflicts.forEach(k => c.append(h("div", "CONFLICT " + k.field + ": " + JSON.stringify(k.values), "err")));
    if (Object.keys(gp.applicability).length) c.append(h("div", "Version applicability: " + JSON.stringify(gp.applicability), "note")); cf.append(c); });
  const fc = h("div", undefined, "card"); fc.append(h("div", "Freshness", "k"), h("div", b.freshness.freshness_basis, "note"), h("div", "Thresholds (hours): " + JSON.stringify(b.freshness.thresholds_hours), "note")); cf.append(fc);
  const dc = h("div", undefined, "card"); dc.append(h("div", "Snapshot diff", "k"));
  if (!b.diff) dc.append(h("div", "No refresh yet; nothing to compare.", "note")); else { dc.append(stat(b.diff.overall)); Object.entries(b.diff.providers).forEach(([n, d]) => { dc.append(h("div", n + ": " + d.state + " " + (d.detail || ""))); Object.entries(d.changed || {}).forEach(([k, ch]) => ch.forEach(c => dc.append(h("div", `  ${k} · ${c.field}: ${JSON.stringify(c.old)} → ${JSON.stringify(c.new)}`, "warn")))); (d.added || []).forEach(a => dc.append(h("div", "  added: " + a, "warn"))); (d.absent_in_latest || []).forEach(a => dc.append(h("div", "  absent (removal not confirmed): " + a, "warn"))); }); }
  cf.append(dc, Object.assign(h("div", "Next: " + b.recommended_next_action, "card")));
}
async function loadProv() { const v = $("#provv"); try { const j = await api("/api/v1/providers/health"); v.replaceChildren(h("div", j.mode + " — " + j.note, "note"), table(["Provider", "Configured", "Status", "Last result"], Object.entries(j.providers).map(([n, p]) => [n, String(p.configured), stat(p.status), p.last_result]))); const m = $("#mode"); m.textContent = j.mode === "LIVE" ? "LIVE" : "DEMO FIXTURES — not live research"; m.className = "pill" + (j.mode === "LIVE" ? "" : " demo"); } catch (e) { v.textContent = "Error: " + e.message; } }
async function loadSet() { const v = $("#setv"); try { const j = await api("/api/v1/settings"); v.replaceChildren(table(["Setting", "Value"], Object.entries(j).filter(([k]) => k !== "secrets").concat(Object.entries(j.secrets).map(([k, s]) => [k, s])))); v.append(h("div", "Defaults are set via environment variables (see .env.example). Secret values are never shown.", "note")); } catch (e) { v.textContent = "Error: " + e.message; } }
loadProv();
