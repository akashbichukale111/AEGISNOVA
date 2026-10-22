// C. Schedule Studio — server-side validation drives the preview; every action is a real API call.
import { h, api, panel, pill, btn, table, empty, toast, confirmDialog, select, absTime, rel, label, session, errorBox, ApiError, prefs, kv } from "../lib.js";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const can = (p) => (session.me?.permissions || []).includes(p);
const TZS = ["UTC", "Asia/Kolkata", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Asia/Tokyo", "Australia/Sydney"];

export default function (ctx) {
  const root = h("div", { class: "split" });
  const left = h("div"), right = h("div", { class: "stack" });
  root.append(left, right);
  let repos = [];
  const formHost = h("div");
  const openForm = (existing) => { clear(formHost); formHost.append(form(repos, existing, () => { refresh.refresh(); formHost.replaceChildren(); })); formHost.scrollIntoView({ behavior: "smooth", block: "nearest" }); };
  const clear = (e) => e.replaceChildren();
  right.append(formHost);
  const refresh = ctx.live(left, async () => { const [s, r] = await Promise.all([api("GET", "/api/schedules"), api("GET", "/api/repos")]); repos = r.items; return { s: s.items, r: r.items }; }, (d, rf) => {
    const repoName = (id) => d.r.find((x) => x.id === id)?.name || id;
    return panel("Schedules", h("div", h("div", { class: "toolbar" }, btn("New schedule", { kind: "primary", ic: "plus", disabled: !can("operate"), reason: "requires the operator role", onclick: () => openForm(null) }), h("span", { class: "grow" }), h("span", { class: "mute" }, "Times shown in ", prefs.tz)),
      d.s.length ? table([
        { h: "Schedule", f: (s) => h("div", h("strong", s.name), h("div", { class: "mute" }, repoName(s.repo_id))) },
        { h: "Status", f: (s) => pill(s.status) },
        { h: "Cadence", f: (s) => s.kind === "one_time" ? "One time" : recText(s.recurrence) + " · " + s.timezone },
        { h: "Next run", f: (s) => s.next_run_at ? h("span", { title: s.next_run_at }, absTime(s.next_run_at), h("div", { class: "mute" }, rel(s.next_run_at))) : "—" },
        { h: "Last run", f: (s) => s.last_run_at ? h("span", {}, absTime(s.last_run_at), h("div", {}, s.last_status && pill(s.last_status))) : h("span", { class: "mute" }, "never") },
        { h: "Mode", f: (s) => (s.allow_repair ? pill("pending", "write-capable") : pill("ok", "read-only")) },
        { h: "Actions", f: (s) => h("div", { class: "row" },
          btn("Edit", { small: true, disabled: !can("operate"), reason: "requires operator", onclick: () => openForm(s) }),
          s.status === "active" ? btn("Pause", { small: true, ic: "pause", disabled: !can("operate"), reason: "requires operator", onclick: () => setStatus(s, "pause", rf) }) : s.status === "paused" || s.status === "disabled" ? btn("Resume", { small: true, ic: "play", disabled: !can("operate"), reason: "requires operator", onclick: () => setStatus(s, "resume", rf) }) : null,
          s.status === "active" ? btn("Disable", { small: true, disabled: !can("operate"), reason: "requires operator", onclick: () => setStatus(s, "disable", rf) }) : s.status === "disabled" ? btn("Enable", { small: true, disabled: !can("operate"), reason: "requires operator", onclick: () => setStatus(s, "enable", rf) }) : null,
          btn("Delete", { small: true, ic: "trash", kind: "danger", disabled: !can("operate"), reason: "requires operator", onclick: () => del(s, rf) })) },
      ], d.s, { aria: "Schedules" }) : empty("No schedules", "Create a recurring read-only inspection to start. Nothing runs until a schedule exists and is active.")));
  }, { ms: 6000 });
  return root;
}

const recText = (r) => !r ? "—" : r.type === "interval" ? `Every ${r.every_minutes} min` : r.type === "daily" ? `Daily at ${r.at}` : `${r.days.join(", ")} at ${r.at}`;
async function setStatus(s, action, rf) {
  try { await api("POST", `/api/schedules/${s.id}/${action}`); toast(`Schedule ${action}d`); rf(); } catch (e) { toast(e.message, "bad"); }
}
async function del(s, rf) {
  const r = await confirmDialog({ title: `Delete schedule “${s.name}”?`, body: "The schedule stops firing. Past runs and jobs remain in the audit history.", confirm: "Delete", danger: true });
  if (!r) return;
  try { await api("DELETE", `/api/schedules/${s.id}`); toast("Schedule deleted"); rf(); } catch (e) { toast(e.message, "bad"); }
}

function form(repos, ex, done) {
  const st = { name: ex?.name || "", purpose: ex?.purpose || "", repo_id: ex?.repo_id || repos[0]?.id || "", kind: ex?.kind || "recurring", timezone: ex?.timezone || prefs.tz, rtype: ex?.recurrence?.type || "daily", at: ex?.recurrence?.at || "02:00", every: ex?.recurrence?.every_minutes || 60, days: new Set(ex?.recurrence?.days || ["mon"]), run_at_local: "", allow_repair: !!ex?.allow_repair, concurrency_policy: ex?.concurrency_policy || "forbid", misfire_policy: ex?.misfire_policy || "skip", misfire_grace_seconds: ex?.misfire_grace_seconds ?? 300, max_duration_seconds: ex?.max_duration_seconds ?? 3600, max_attempts: ex?.retry_policy?.max_attempts ?? 4 };
  const preview = h("div", { class: "stack", "aria-live": "polite" });
  const errs = {};
  const host = h("form", { class: "panel", onsubmit: (e) => e.preventDefault(), novalidate: true });
  const payload = () => {
    const b = { name: st.name, purpose: st.purpose, repo_id: st.repo_id, kind: st.kind, timezone: st.timezone, allow_repair: st.allow_repair, concurrency_policy: st.concurrency_policy, misfire_policy: st.misfire_policy, misfire_grace_seconds: Number(st.misfire_grace_seconds), max_duration_seconds: Number(st.max_duration_seconds), retry_policy: { max_attempts: Number(st.max_attempts) } };
    if (st.kind === "recurring") b.recurrence = st.rtype === "interval" ? { type: "interval", every_minutes: Number(st.every) } : st.rtype === "daily" ? { type: "daily", at: st.at } : { type: "weekly", days: [...st.days], at: st.at };
    else b.run_at_local = st.run_at_local;
    return b;
  };
  let tmr;
  const validate = async () => {
    try {
      const r = await api("POST", "/api/schedules/validate", payload());
      preview.replaceChildren(h("div", { class: "note" }, h("strong", r.recurrence_text), h("div", { class: "mute" }, "Next runs (", st.timezone, "):"), h("ul", r.next_runs.slice(0, 5).map((t) => h("li", h("span", { class: "mono" }, absTime(t, st.timezone)), h("span", { class: "mute" }, "  " + rel(t)))))),
        ...r.warnings.map((w) => h("div", { class: "note warn" }, w)));
      return true;
    } catch (e) { preview.replaceChildren(h("div", { class: "note bad", role: "alert" }, e.message, e.code ? h("div", { class: "mono mute" }, e.code) : null)); return false; }
  };
  const later = () => { clearTimeout(tmr); tmr = setTimeout(validate, 350); };
  const inp = (key, type = "text", extra = {}) => h("input", { class: "inp", type, value: st[key], oninput: (e) => { st[key] = e.target.value; later(); }, ...extra });
  let fid = 0;
  const field = (lbl, ctl, hint) => { const id = "sf" + (++fid); if (ctl.tagName) ctl.id = id; return h("div", { class: "field" }, h("label", { for: id }, lbl), ctl, hint && h("div", { class: "hint" }, hint)); };
  const cadence = h("div", { class: "stack" });
  const drawCadence = () => {
    cadence.replaceChildren(
      st.kind === "one_time" ? field("Run at (local time in the selected timezone)", inp("run_at_local", "datetime-local")) :
      h("div", { class: "stack" }, h("div", { class: "f2" }, field("Recurrence", select([["interval", "Every N minutes"], ["daily", "Daily"], ["weekly", "Weekly"]], st.rtype, (v) => { st.rtype = v; drawCadence(); later(); }, "Recurrence type")),
        st.rtype === "interval" ? field("Every (minutes)", inp("every", "number", { min: 1, max: 44640 })) : field("At (HH:MM, 24h)", inp("at", "text", { placeholder: "02:00", maxlength: 5 }))),
      st.rtype === "weekly" && h("div", { class: "field" }, h("div", { class: "lbl" }, "Days"), h("div", { class: "row" }, DAYS.map((d) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: st.days.has(d), onchange: (e) => { e.target.checked ? st.days.add(d) : st.days.delete(d); later(); } }), d))))));
  };
  drawCadence();
  const repoSel = select(repos.map((r) => [r.id, r.name + (r.allow_repair ? "" : " (read-only)")]), st.repo_id, (v) => { st.repo_id = v; later(); }, "Repository");
  const write = h("input", { type: "checkbox", checked: st.allow_repair, disabled: !can("authorize_repair"), onchange: (e) => { st.allow_repair = e.target.checked; later(); } });
  host.append(h("header", { class: "panel-h" }, h("h2", ex ? "Edit schedule" : "New schedule"), h("span", { class: "grow" }), btn("Close", { small: true, onclick: done })),
    h("div", { class: "panel-b form" },
      h("div", { class: "f2" }, field("Name", inp("name", "text", { maxlength: 80 })), field("Repository", repoSel)),
      field("Purpose", inp("purpose", "text", { maxlength: 500, placeholder: "e.g. nightly read-only dependency inspection" })),
      h("div", { class: "f2" }, field("Type", select([["recurring", "Recurring"], ["one_time", "One-time"]], st.kind, (v) => { st.kind = v; drawCadence(); later(); }, "Schedule type")),
        field("Timezone (IANA)", h("input", { class: "inp", list: "tzs", value: st.timezone, oninput: (e) => { st.timezone = e.target.value; later(); } }), "DST gaps shift forward; ambiguous times use the first occurrence.")),
      h("datalist", { id: "tzs" }, TZS.map((z) => h("option", { value: z }))),
      cadence,
      h("div", { class: "f3" }, field("Concurrency", select([["forbid", "Forbid overlap"], ["allow", "Allow overlap"]], st.concurrency_policy, (v) => { st.concurrency_policy = v; later(); }, "Concurrency")),
        field("If a run was missed", select([["skip", "Skip"], ["run_once", "Run once (catch up)"]], st.misfire_policy, (v) => { st.misfire_policy = v; later(); }, "Missed-run policy")),
        field("Grace (s)", inp("misfire_grace_seconds", "number", { min: 0, max: 86400 }))),
      h("div", { class: "f2" }, field("Max job duration (s)", inp("max_duration_seconds", "number", { min: 60, max: 86400 })), field("Retry attempts (max)", inp("max_attempts", "number", { min: 1, max: 10 }), "Exponential backoff with jitter; permanent errors are never retried.")),
      h("label", { class: "check" }, write, h("span", h("strong", "Allow write-capable repair proposals"), h("div", { class: "hint" }, can("authorize_repair") ? "Scheduling is not authorisation: each repair still needs a scoped approval, passing tests and independent verification." : "Requires the approver or admin role."))),
      preview,
      h("div", { class: "row" }, btn("Validate", { ic: "check", onclick: validate }),
        btn(ex ? "Save changes" : "Create schedule", { kind: "primary", disabled: !can("operate"), reason: "requires operator", onclick: async () => {
          if (!(await validate())) return;
          try { ex ? await api("PATCH", `/api/schedules/${ex.id}`, payload()) : await api("POST", "/api/schedules", payload()); toast(ex ? "Schedule updated" : "Schedule created"); done(); } catch (e) { toast(e.message, "bad"); preview.append(h("div", { class: "note bad", role: "alert" }, e.message)); }
        } }))));
  if (ex || st.name) later();
  return host;
}
