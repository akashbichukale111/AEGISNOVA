// H. Settings & Provider Health — redacted configuration, honest labels (live / unconfigured / stubbed / not implemented).
import { h, api, panel, pill, btn, kv, table, empty, toast, absTime, rel, label, mono, session } from "../lib.js";

const can = (p) => (session.me?.permissions || []).includes(p);
const STATUS_TEXT = { ok: "Live", built_in: "Built-in", stub: "Dev stub", not_implemented: "Not implemented", not_configured: "Not configured", configured: "Configured", disabled: "Disabled", blocked: "Blocked", unavailable: "Unavailable" };

export default function (ctx) {
  const root = h("div");
  ctx.live(root, () => api("GET", "/api/settings"), (s, rf) => {
    const check = async (id) => { try { const r = await api("POST", `/api/providers/${id}/check`); toast(r.ok ? `${id}: check passed (${r.latency_ms} ms)` : `${id}: check failed (${r.error_code || "error"})`, r.ok ? "good" : "bad"); rf(); } catch (e) { toast(e.message, "bad"); } };
    return h("div", { class: "stack" },
      h("div", { class: "note" }, "Secret values are never displayed. Status words describe what this standalone build actually does: ", h("strong", "Live"), " means a real check succeeded; ", h("strong", "Dev stub"), ", ", h("strong", "Not implemented"), " and ", h("strong", "Not configured"), " are shown as they are."),
      panel("Components", table([{ h: "Component", f: (c) => h("strong", c.label) }, { h: "Status", f: (c) => pill(c.status, STATUS_TEXT[c.status] || label(c.status)) }, { h: "Mode", f: (c) => c.mode }, { h: "Detail", f: (c) => c.detail }], s.components, { aria: "Components" })),
      panel("Advisory providers", table([{ h: "Provider", f: (p) => p.label }, { h: "Mode", f: (p) => p.mode }, { h: "Status", f: (p) => pill(p.status) }, { h: "Last success", f: (p) => (p.last_success_at ? rel(p.last_success_at) : "never") }, { h: "Failures", f: (p) => p.consecutive_failures, cls: "num" }, { h: "Detail", f: (p) => p.detail }, { h: "", f: (p) => (p.configured ? btn("Check now", { small: true, ic: "refresh", disabled: !can("operate"), reason: "requires operator", onclick: () => check(p.provider) }) : null) }], s.providers, { aria: "Providers" })),
      h("div", { class: "grid g2" },
        panel("Execution sandbox", h("div", { class: "panel-b stack" }, kv([["Available", s.sandbox.available ? pill("ok", "yes") : pill("blocked", "no — repairs fail closed")], ["Backend", s.sandbox.backend], ["Reason", s.sandbox.reason || "—"]]),
          h("div", { class: "note warn" }, "Network isolation, resource limits, env scrubbing and an allowlisted command catalogue are enforced. There is NO filesystem confinement: run on a disposable host/container for untrusted repositories."),
          h("div", { class: "mute" }, "Allowlisted commands"), h("div", { class: "chips" }, Object.entries(s.command_catalogue).map(([k, v]) => h("span", { class: "chip", title: String(v) }, k))))),
        panel("Runtime configuration", h("div", { class: "panel-b" }, kv(Object.entries(s.config).map(([k, v]) => [label(k), String(v)])), h("p", { class: "mute" }, `Workflow ${s.workflow_version} · process started ${absTime(s.started_at)}`)))),
      panel("Risk policies (deterministic)", h("div", { class: "grid g2 panel-b" }, s.policies.map((p) => h("div", h("strong", `${p.name} v${p.version}`), h("pre", { class: "code" }, JSON.stringify(p.body, null, 2)))))));
  }, { ms: 10000 });
  return root;
}
