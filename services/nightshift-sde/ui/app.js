// NightShift SDE console — shell, auth, hash router, bounded polling with honest staleness indicators.
import { h, clear, api, session, store, prefs, toast, btn, errorBox, loading, rel, ApiError, label, pill } from "./lib.js";
import { icon } from "./icons.js";

const ROUTES = [
  ["", "Command Center", "gauge", () => import("./views/overview.js")],
  ["jobs", "Jobs", "activity", () => import("./views/jobs.js")],
  ["schedules", "Schedule Studio", "calendar", () => import("./views/schedules.js")],
  ["fleet", "Repository Fleet", "branch", () => import("./views/fleet.js")],
  ["dependencies", "Dependency Intelligence", "shield", () => import("./views/deps.js")],
  ["recovery", "Recovery & Reliability", "rescue", () => import("./views/recovery.js")],
  ["audit", "Evidence & Audit", "scroll", () => import("./views/audit.js")],
  ["settings", "Settings & Providers", "settings", () => import("./views/settings.js")],
];
const POLL_MAX_AGE_MS = 20000;
const app = document.getElementById("app");
let cleanups = [];
let fresh = { ok: null, err: null, el: null };
let navBadges = {};

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  return { parts, query: Object.fromEntries(new URLSearchParams(query)) };
}
export function navigate(path, replace = false) {
  const url = "#/" + path.replace(/^\//, "");
  if (replace) history.replaceState(null, "", url), render(); else location.hash = url;
}

// --------------------------------------------------------------------------------------------- freshness indicator
function paintFresh() {
  if (!fresh.el) return;
  const el = fresh.el;
  el.className = "fresh";
  clear(el);
  if (fresh.err && (!fresh.ok || Date.now() - fresh.ok > 1000)) {
    el.classList.add("err");
    el.append(h("i", { class: "dot" }), `Disconnected — showing data from ${fresh.ok ? rel(new Date(fresh.ok).toISOString()) : "never"}`);
    el.setAttribute("title", fresh.err);
  } else if (fresh.ok && Date.now() - fresh.ok > POLL_MAX_AGE_MS) {
    el.classList.add("stale");
    el.append(h("i", { class: "dot" }), `Stale — updated ${rel(new Date(fresh.ok).toISOString())}`);
  } else if (fresh.ok) {
    el.append(h("i", { class: "dot" }), `Polled ${rel(new Date(fresh.ok).toISOString())}`);
    el.removeAttribute("title");
  } else el.append(h("i", { class: "dot" }), "Waiting for data…");
}
setInterval(paintFresh, 1000);

// --------------------------------------------------------------------------------------------- view context
function makeCtx(route) {
  const { parts, query } = parseHash();
  const ctx = {
    params: { id: parts[1] || null }, query,
    setQuery(obj, replace = true) {
      const q = { ...query, ...obj };
      for (const k of Object.keys(q)) if (q[k] === "" || q[k] === null || q[k] === undefined) delete q[k];
      const s = new URLSearchParams(q).toString();
      navigate((parts.join("/")) + (s ? "?" + s : ""), replace);
    },
    onCleanup(fn) { cleanups.push(fn); },
    /** live(container, load, renderFn, {ms}) — load → render; bounded polling; stale-data aware; skips redraw when data is unchanged. */
    live(container, load, renderFn, { ms = 5000, poll = true } = {}) {
      let last = null, timer = null, dead = false, inflight = false, first = true;
      const run = async (force = false) => {
        if (dead || inflight) return;
        inflight = true;
        try {
          const data = await load();
          if (dead) return;
          fresh.ok = Date.now(); fresh.err = null; paintFresh();
          const sig = JSON.stringify(data);
          if (force || sig !== last) {
            last = sig;
            const scroll = window.scrollY;
            clear(container).append(renderFn(data, () => run(true)));
            if (!first) window.scrollTo({ top: scroll });
          }
          first = false;
        } catch (e) {
          if (dead) return;
          if (e instanceof ApiError && e.status === 401) return;
          fresh.err = e.message; paintFresh();
          if (first || last === null) clear(container).append(errorBox(e, () => { clear(container).append(loading()); run(true); }));
        } finally { inflight = false; }
      };
      clear(container).append(loading());
      run(true);
      const tick = () => { if (!document.hidden && poll) run(); };
      if (poll) timer = setInterval(tick, ms);
      const vis = () => { if (!document.hidden) run(); };
      document.addEventListener("visibilitychange", vis);
      cleanups.push(() => { dead = true; clearInterval(timer); document.removeEventListener("visibilitychange", vis); });
      return { refresh: () => run(true) };
    },
  };
  return ctx;
}

// --------------------------------------------------------------------------------------------- shell
async function loadBadges() {
  try {
    const o = await api("GET", "/api/overview");
    navBadges = { jobs: o.active_jobs.length || 0, recovery: (o.alerts.length || 0) + (o.dead_letter || 0), "": o.approvals.pending || 0 };
    document.querySelectorAll("[data-badge]").forEach((n) => {
      const v = navBadges[n.dataset.badge] || 0;
      n.textContent = v ? String(v) : ""; n.hidden = !v; n.classList.toggle("hot", n.dataset.badge === "recovery" && v > 0);
    });
    fresh.ok = Date.now(); fresh.err = null;
  } catch (e) { fresh.err = e.message; }
  paintFresh();
}
let badgeTimer = null;

async function render() {
  cleanups.forEach((f) => { try { f(); } catch { /* ignore */ } });
  cleanups = [];
  if (!session.token) return renderLogin();
  if (!session.me) {
    try { session.me = await api("GET", "/api/me"); } catch (e) { if (e.status === 401) return renderLogin("That token was not accepted."); return renderFatal(e); }
  }
  const { parts } = parseHash();
  const key = parts[0] || "";
  const route = ROUTES.find((r) => r[0] === key) || ROUTES[0];
  const shell = h("div", { class: "shell" });
  const nav = h("nav", { class: "nav", "aria-label": "Primary" },
    h("div", { class: "brand" }, h("div", { class: "mark", "aria-hidden": "true" }, h("i")), h("div", h("b", "NightShift SDE"), h("small", "AEGISNOVA · internal"))),
    ROUTES.map(([k, name, ic]) => h("a", { class: "item", href: "#/" + k, "aria-current": k === route[0] ? "page" : null, title: name }, icon(ic), h("span", { class: "lbl" }, name),
      (k === "" || k === "jobs" || k === "recovery") && h("span", { class: "badge", "data-badge": k, hidden: true }))),
    h("div", { class: "foot" }, "Standalone build · not merged into the AEGISNOVA app"));
  fresh.el = h("span", { class: "fresh", role: "status", "aria-live": "off" });
  const tzSel = h("select", { class: "inp", "aria-label": "Display timezone", onchange: (e) => { prefs.tz = e.target.value; store.setLocal("ns.tz", prefs.tz); render(); } },
    [...new Set([prefs.tz, "UTC", "Asia/Kolkata", "Europe/London", "America/New_York", "America/Los_Angeles", "Europe/Berlin", "Asia/Tokyo", "Australia/Sydney"])].map((z) => h("option", { value: z, selected: z === prefs.tz }, z)));
  const top = h("header", { class: "top" },
    h("h1", route[1]), h("span", { class: "grow" }), fresh.el, tzSel,
    h("span", { class: "pill t-info", title: "Your role (server-enforced)" }, icon("key", 14), `${session.me.actor} · ${session.me.role}`),
    btn("Sign out", { ic: "logout", small: true, onclick: () => { store.del("ns.token"); session.token = null; session.me = null; render(); } }));
  const content = h("main", { id: "main", class: "content", tabindex: "-1" });
  shell.append(nav, h("div", { class: "main" }, top, content));
  clear(app).append(shell);
  paintFresh();
  document.title = `${route[1]} · NightShift SDE`;
  const ctx = makeCtx(route);
  try {
    const mod = await route[3]();
    const node = await mod.default(ctx);
    content.append(node);
  } catch (e) { content.append(errorBox(e)); }
  loadBadges();
  clearInterval(badgeTimer);
  badgeTimer = setInterval(() => { if (!document.hidden) loadBadges(); }, 10000);
  cleanups.push(() => clearInterval(badgeTimer));
}

function renderLogin(msg) {
  const input = h("input", { class: "inp", type: "password", autocomplete: "off", spellcheck: "false", placeholder: "nsd_…", "aria-label": "API token", style: null, id: "tok" });
  const err = h("div", { class: "err mute", role: "alert" }, msg || "");
  const go = async (e) => {
    e.preventDefault();
    session.token = input.value.trim();
    session.me = null;
    try { session.me = await api("GET", "/api/me"); store.setSession("ns.token", session.token); render(); }
    catch (ex) { session.token = null; clear(err).append(ex.status === 401 ? "That token was not accepted." : ex.message); }
  };
  clear(app).append(h("div", { class: "login" }, h("form", { class: "panel card", onsubmit: go },
    h("div", { class: "brand" }, h("div", { class: "mark" }, h("i")), h("div", h("b", "NightShift SDE"), h("small", "AEGISNOVA · A New Standard for Safe AI"))),
    h("h1", "Engineering Command Center"),
    h("p", { class: "mute" }, "Sign in with a bearer token. Local tokens are generated at init into a private file; print one with ", h("code", "python -m nightshift token admin"), ". The token is kept in this tab's session storage only."),
    h("div", { class: "field" }, h("label", { for: "tok" }, "API token"), input, err),
    h("div", { class: "row" }, btn("Sign in", { kind: "primary", type: "submit", ic: "lock" })))));
  input.focus();
}
function renderFatal(e) { clear(app).append(h("div", { class: "login" }, h("div", { class: "card panel" }, errorBox(e, () => render())))); }

session.onUnauthorized = () => { if (session.me) { store.del("ns.token"); session.token = null; session.me = null; toast("Session expired or token revoked — please sign in again.", "bad"); render(); } };
window.addEventListener("hashchange", render);
render();
