// Minimal stroke icon set (24x24, 1.75 stroke). Built with DOM APIs so it works under a strict CSP.
const P = {
  gauge: ["M12 14l4-4", "M3.3 17a9 9 0 1 1 17.4 0", "M12 14h.01"],
  activity: ["M3 12h4l3-8 4 16 3-8h4"],
  calendar: ["M4 6h16v14H4z", "M4 10h16", "M8 3v4", "M16 3v4"],
  branch: ["M6 3v12", "M18 9a3 3 0 1 0 0 .01", "M6 18a3 3 0 1 0 0 .01", "M18 12a9 9 0 0 1-9 9"],
  shield: ["M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", "M9 12l2 2 4-4"],
  rescue: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0", "M12 12m-3.5 0a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0", "M5.6 5.6l3 3", "M15.4 15.4l3 3", "M18.4 5.6l-3 3", "M8.6 15.4l-3 3"],
  scroll: ["M8 4h11v13a3 3 0 0 1-3 3H6", "M8 4a3 3 0 0 0-3 3v1h3", "M6 20a3 3 0 0 1-3-3v-1h13", "M11 9h5", "M11 13h5"],
  settings: ["M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"],
  play: ["M7 4l13 8-13 8z"],
  pause: ["M8 5v14", "M16 5v14"],
  x: ["M6 6l12 12", "M18 6L6 18"],
  check: ["M5 12l5 5 9-10"],
  refresh: ["M20 11a8 8 0 0 0-14.9-3M4 4v4h4", "M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"],
  alert: ["M12 3l10 18H2z", "M12 10v5", "M12 18h.01"],
  lock: ["M5 11h14v10H5z", "M8 11V7a4 4 0 0 1 8 0v4"],
  clock: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0", "M12 7v5l3 2"],
  search: ["M11 11m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0", "M21 21l-5-5"],
  "chev-left": ["M15 5l-7 7 7 7"],
  "chev-right": ["M9 5l7 7-7 7"],
  inbox: ["M3 13l3-8h12l3 8", "M3 13v6h18v-6", "M3 13h5a4 4 0 0 0 8 0h5"],
  plus: ["M12 5v14", "M5 12h14"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13"],
  bolt: ["M13 3L5 14h6l-1 7 8-11h-6z"],
  key: ["M14 10a4 4 0 1 1-4-4 4 4 0 0 1 4 4z", "M13 13l7 7", "M17 17l2-2"],
  logout: ["M9 4H5v16h4", "M16 8l4 4-4 4", "M20 12H9"],
  link: ["M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1", "M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"],
  eye: ["M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z", "M12 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0-6 0"],
  stop: ["M6 6h12v12H6z"],
  rewind: ["M11 6l-8 6 8 6z", "M21 6l-8 6 8 6z"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
};
export function icon(name, size = 18) {
  const NS = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", size); s.setAttribute("height", size);
  s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.75");
  s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false");
  s.setAttribute("class", "ic");
  for (const d of P[name] || P.alert) { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); s.append(p); }
  return s;
}
