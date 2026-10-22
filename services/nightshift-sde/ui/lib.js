// Tiny DOM + API toolkit. All server data is inserted as text nodes (XSS-safe by construction).
import { icon } from "./icons.js";

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs && typeof attrs === "object" && !(attrs instanceof Node) && !Array.isArray(attrs)) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k === "value") el.value = v;
      else if (k === "checked" || k === "disabled" || k === "selected" || k === "open") el[k] = !!v;
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  } else if (attrs !== undefined && attrs !== null) kids.unshift(attrs);
  add(el, kids);
  return el;
}
function add(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}
export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

// ----------------------------------------------------------------------------------------------- storage (always guarded)
export const store = {
  get(k, d = null) { try { const v = sessionStorage.getItem(k) ?? localStorage.getItem(k); return v ?? d; } catch { return d; } },
  setSession(k, v) { try { sessionStorage.setItem(k, v); } catch { /* storage may be unavailable */ } },
  setLocal(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  del(k) { try { sessionStorage.removeItem(k); localStorage.removeItem(k); } catch { /* ignore */ } },
};

// ----------------------------------------------------------------------------------------------- API
export class ApiError extends Error {
  constructor(status, code, message, corr, details) { super(message); this.status = status; this.code = code; this.corr = corr; this.details = details; }
}
export const session = { token: store.get("ns.token"), me: null, onUnauthorized: () => {} };

export async function api(method, path, body, opts = {}) {
  const headers = { Accept: "application/json" };
  if (session.token) headers.Authorization = "Bearer " + session.token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: opts.signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK", "Cannot reach the NightShift server. Is it running?", null);
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) {
    const e = data?.error || {};
    if (res.status === 401) session.onUnauthorized();
    throw new ApiError(res.status, e.code || "HTTP_" + res.status, e.message || res.statusText, e.correlation_id || res.headers.get("X-Correlation-ID"), e.details);
  }
  return data;
}
export const qs = (o) => { const p = new URLSearchParams(); for (const [k, v] of Object.entries(o)) if (v !== "" && v !== null && v !== undefined) p.set(k, v); const s = p.toString(); return s ? "?" + s : ""; };
export const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());

// ----------------------------------------------------------------------------------------------- formatting
// Browsers may report legacy IANA aliases that the server's tz database does not carry; map the common ones to canonical names.
const TZ_ALIAS = { "Asia/Calcutta": "Asia/Kolkata", "Asia/Katmandu": "Asia/Kathmandu", "Asia/Saigon": "Asia/Ho_Chi_Minh", "Asia/Rangoon": "Asia/Yangon", "America/Buenos_Aires": "America/Argentina/Buenos_Aires", "Europe/Kiev": "Europe/Kyiv" };
const canonTz = (z) => TZ_ALIAS[z] || z;
export const prefs = { tz: canonTz(store.get("ns.tz") || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC") };
export function absTime(iso, tz = prefs.tz) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  try { return new Intl.DateTimeFormat("en-GB", { timeZone: tz, year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d); }
  catch { return d.toISOString(); }
}
export function dur(sec) {
  if (sec === null || sec === undefined || isNaN(sec)) return "—";
  sec = Math.max(0, Math.round(sec));
  if (sec < 1) return "<1s";
  if (sec < 60) return sec + "s";
  if (sec < 3600) return Math.floor(sec / 60) + "m " + (sec % 60) + "s";
  if (sec < 86400) return Math.floor(sec / 3600) + "h " + Math.floor((sec % 3600) / 60) + "m";
  return Math.floor(sec / 86400) + "d " + Math.floor((sec % 86400) / 3600) + "h";
}
export function rel(iso, now = Date.now()) {
  if (!iso) return "—";
  const s = (now - new Date(iso).getTime()) / 1000;
  if (isNaN(s)) return String(iso);
  return s >= 0 ? dur(s) + " ago" : "in " + dur(-s);
}
export const short = (s, n = 8) => (s ? String(s).slice(0, n) : "—");
export const num = (n) => (n === null || n === undefined ? "—" : new Intl.NumberFormat("en-GB").format(n));

// ----------------------------------------------------------------------------------------------- tones & labels
const GOOD = new Set(["confirmed", "COMPLETED", "ok", "healthy", "approved", "repair_verified", "no_findings", "configured", "fired", "catchup_fired", "active", "pass", "passed", "live", "local-file", "built_in"]);
const WARN = new Set(["COMPLETED_WITH_WARNINGS", "WAITING_FOR_APPROVAL", "RETRY_WAIT", "PAUSED", "degraded", "pending", "stub", "stale", "paused", "investigation_only", "repair_blocked", "unverified", "medium", "missed_skipped", "skipped_concurrency", "conflicting"]);
const BAD = new Set(["FAILED", "DEAD_LETTER", "EXPIRED", "down", "rejected", "revoked", "expired", "blocked", "unavailable", "dead_lettered", "failed", "error", "critical", "high", "CRITICAL", "HIGH", ]);
const INFO = new Set(["QUEUED", "VALIDATING", "SNAPSHOTTING", "INSPECTING", "RESEARCHING", "EVIDENCE_REVIEW", "RISK_ASSESSMENT", "READY_TO_EXECUTE", "EXECUTING", "TESTING", "INDEPENDENT_VERIFICATION", "CREATED"]);
export function tone(v) {
  if (GOOD.has(v)) return "good"; if (WARN.has(v)) return "warn"; if (BAD.has(v)) return "bad"; if (INFO.has(v)) return "info"; return "mute";
}
export const label = (s) => (s ? String(s).replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "—");
export function pill(value, text, extra = "") {
  return h("span", { class: `pill t-${tone(value)} ${extra}` }, h("i", { class: "dot", "aria-hidden": "true" }), text ?? label(value));
}
export const sevTone = { CRITICAL: "critical", HIGH: "high", MEDIUM: "medium", LOW: "low", UNKNOWN: "unknown" };
export function sevBadge(sev) { return h("span", { class: `sev sev-${(sev || "unknown").toLowerCase()}` }, sev || "UNKNOWN"); }

// ----------------------------------------------------------------------------------------------- shared components
export function btn(text, opts = {}) {
  const { ic, kind = "ghost", onclick, disabled, reason, small, type = "button" } = opts;
  const b = h("button", { class: `btn btn-${kind}${small ? " btn-sm" : ""}`, type, onclick, disabled: !!disabled,
    title: disabled && reason ? reason : opts.title, "aria-disabled": disabled ? "true" : null, "aria-describedby": null },
  ic ? icon(ic) : null, text ? h("span", text) : null);
  if (opts.label) b.setAttribute("aria-label", opts.label);
  if (disabled && reason) b.append(h("span", { class: "sr" }, ` (disabled: ${reason})`));
  return b;
}
export function panel(title, body, opts = {}) {
  return h("section", { class: `panel ${opts.class || ""}`, "aria-label": typeof title === "string" ? title : opts.aria },
    (title || opts.actions) && h("header", { class: "panel-h" }, h("h2", title), opts.sub && h("span", { class: "sub" }, opts.sub), h("span", { class: "grow" }), opts.actions),
    body);
}
export const empty = (title, hint, extra) => h("div", { class: "empty" }, icon("inbox"), h("strong", title), hint && h("p", hint), extra);
export const errorBox = (e, retry) => h("div", { class: "errbox", role: "alert" }, icon("alert"), h("div", h("strong", e instanceof ApiError ? `${e.code}: ` : "", e.message || String(e)),
  e.corr ? h("div", { class: "mono mute" }, "correlation ", e.corr) : null), retry && btn("Retry", { ic: "refresh", onclick: retry, small: true }));
export const loading = (t = "Loading…") => h("div", { class: "loading", role: "status" }, h("span", { class: "spin" }), t);
export const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(Boolean).flatMap(([k, v, cls]) => [h("dt", k), h("dd", { class: cls || "" }, v ?? "—")]));
export const mono = (t) => h("span", { class: "mono" }, t);
export function copyable(text, shown) {
  return h("button", { class: "copy mono", type: "button", title: "Copy", onclick: async (e) => { try { await navigator.clipboard.writeText(text); toast("Copied"); } catch { toast("Copy not available", "bad"); } e.currentTarget.blur(); } }, shown ?? text);
}
export function table(cols, rows, opts = {}) {
  return h("div", { class: "tablewrap", tabindex: "0", role: "region", "aria-label": opts.aria || "table" },
    h("table", { class: "tbl" },
      h("thead", h("tr", cols.map((c) => h("th", { scope: "col", class: c.cls || "" }, c.h)))),
      h("tbody", rows.map((r) => h("tr", { class: opts.rowClass ? opts.rowClass(r) : "" }, cols.map((c) => h("td", { class: c.cls || "" }, c.f(r))))))));
}
export function pager(page, onGo) {
  const { total, limit, offset } = page;
  if (!total) return null;
  const from = offset + 1, to = Math.min(offset + limit, total);
  return h("nav", { class: "pager", "aria-label": "Pagination" }, h("span", { class: "mute" }, `${from}–${to} of ${num(total)}`), h("span", { class: "grow" }),
    btn("Previous", { small: true, ic: "chev-left", disabled: offset <= 0, onclick: () => onGo(Math.max(0, offset - limit)) }),
    btn("Next", { small: true, ic: "chev-right", disabled: page.next_offset === null || page.next_offset === undefined, onclick: () => onGo(page.next_offset) }));
}

// toasts + confirm dialog
export function toast(msg, kind = "good") {
  let host = document.getElementById("toasts");
  if (!host) { host = h("div", { id: "toasts", role: "status", "aria-live": "polite" }); document.body.append(host); }
  const t = h("div", { class: `toast t-${kind}` }, msg);
  host.append(t);
  setTimeout(() => t.remove(), 5000);
}
export function confirmDialog({ title, body, confirm = "Confirm", danger = false, input = null }) {
  return new Promise((resolve) => {
    const field = input ? h("textarea", { class: "inp", rows: 2, maxlength: 400, placeholder: input, "aria-label": input }) : null;
    const dlg = h("dialog", { class: "dlg", "aria-labelledby": "dlg-t" },
      h("form", { method: "dialog", onsubmit: (e) => e.preventDefault() },
        h("h2", { id: "dlg-t" }, title), h("div", { class: "dlg-b" }, body), field,
        h("div", { class: "dlg-f" },
          btn("Cancel", { onclick: () => { dlg.close(); resolve(null); } }),
          btn(confirm, { kind: danger ? "danger" : "primary", onclick: () => { dlg.close(); resolve({ ok: true, note: field ? field.value : "" }); } }))));
    dlg.addEventListener("cancel", () => resolve(null));
    dlg.addEventListener("close", () => dlg.remove());
    document.body.append(dlg);
    dlg.showModal();
    dlg.querySelector("button:last-of-type")?.focus();
  });
}
// Simple chips for filters
export function select(opts, value, onchange, aria) {
  return h("select", { class: "inp", "aria-label": aria, onchange: (e) => onchange(e.target.value) }, opts.map(([v, t]) => h("option", { value: v, selected: v === (value ?? "") }, t)));
}
