// Browser integrity signals for the interview room: tab switches, window focus loss, leaving full screen, copy and
// paste, a second screen, browser extensions. They go to the recruiter as context; they are never scored, and
// pasted text itself is never sent.
//
// Strict mode (a role setting) also blocks copy, paste, cut, right-click and text selection, and tells the room
// when the candidate leaves full screen so it can pause the interview.
//
// What a web page cannot do: list or switch off extensions, see a second device, or stop a determined person. The
// checks below catch common setups and are reported as signals, not proof.

const MIN_AWAY_SEC = 1.5; // shorter blips (a notification, an alt-tab slip) are not worth a line in a report

// Extensions that write into every page leave marks a page can read. Known names first; any other custom element
// or extension resource is reported by its tag or origin, because this page itself uses neither.
const KNOWN = [
  ["Grammarly", () => document.documentElement.hasAttribute("data-gr-ext-installed") || document.body?.hasAttribute("data-new-gr-c-s-check-loaded") || document.querySelector("grammarly-desktop-integration, grammarly-extension")],
  ["LanguageTool", () => document.documentElement.hasAttribute("data-lt-installed") || document.querySelector("lt-toolbar, lt-div")],
  ["Monica", () => document.querySelector("#monica-content-root, [id^='monica-']")],
  ["Sider", () => document.querySelector("#sider-ai-root, [id^='sider-']")],
  ["Merlin", () => document.querySelector("#merlin-root, [id^='merlin-']")],
  ["MaxAI", () => document.querySelector("#MAXAI_ROOT, [id^='maxai']")],
  ["HARPA AI", () => document.querySelector("harpa-app, #harpa-ai")],
];
const EXTENSION_URL = /^(chrome|moz|safari-web|ms-browser)-extension:\/\//;

export function detectExtensions() {
  const found = new Set(KNOWN.filter(([, test]) => { try { return !!test(); } catch { return false; } }).map(([name]) => name));
  if (!found.size) {
    for (const el of document.querySelectorAll("*")) {
      if (el.tagName.includes("-")) { found.add(`Unknown extension (${el.tagName.toLowerCase()})`); break; }
    }
  }
  const urls = [...performance.getEntriesByType("resource").map((e) => e.name), ...[...document.querySelectorAll("[src], link[href]")].map((e) => e.src || e.href)];
  for (const url of urls) {
    if (EXTENSION_URL.test(url)) { found.add(`Extension resource (${new URL(url).protocol.replace(":", "")})`); break; }
  }
  return [...found].slice(0, 10);
}

// Extensions inject a moment after the page loads; check twice.
export function checkExtensions() {
  return new Promise((resolve) => setTimeout(() => resolve(detectExtensions()), 1200));
}

export function startMonitor({ clock, send, notify, strict = false, onFullscreen = () => {} }) {
  let queue = [], away = null;
  const push = (e) => { queue.push({ at_sec: Math.round(clock() * 10) / 10, ...e }); };

  const flush = (keepalive = false) => {
    if (!queue.length) return;
    const events = queue.splice(0, 50);
    send(events, keepalive).catch(() => queue.unshift(...events)); // try again on the next tick
  };

  // One "away" span at a time, labelled by its first signal. Browsers cannot reliably tell a tab switch from a window
  // switch (macOS reports a covered window as a hidden tab), so the report shows both as one check.
  const leave = (kind) => { if (!away) { away = { kind, t: Date.now() }; notify("You left the interview. This is noted for the hiring team."); } };
  const back = () => {
    if (!away) return;
    const seconds = (Date.now() - away.t) / 1000;
    if (seconds >= MIN_AWAY_SEC) push({ kind: away.kind, seconds: Math.round(seconds * 10) / 10 });
    away = null;
  };
  const block = (what) => (e) => {
    if (!strict) return what === "paste" ? push({ kind: "paste", detail: `${(e.clipboardData?.getData("text") || "").length} characters` }) : what === "copy" && push({ kind: "copy" });
    e.preventDefault();
    push({ kind: "blocked", detail: what });
    notify(`${what[0].toUpperCase()}${what.slice(1)} is turned off in this interview.`);
  };

  const on = (target, name, fn) => { target.addEventListener(name, fn); return () => target.removeEventListener(name, fn); };
  const off = [
    on(document, "visibilitychange", () => (document.hidden ? leave("tab_hidden") : back())),
    on(window, "blur", () => leave("window_blur")),
    on(window, "focus", () => !document.hidden && back()),
    on(document, "fullscreenchange", () => {
      const full = !!document.fullscreenElement;
      if (!full) leave("fullscreen_exit"); else if (away?.kind === "fullscreen_exit") back();
      onFullscreen(full);
    }),
    on(document, "copy", block("copy")),
    on(document, "cut", block("cut")),
    on(document, "paste", block("paste")),
    on(window, "pagehide", () => { back(); flush(true); }),
  ];
  if (strict) {
    off.push(on(document, "contextmenu", block("right-click")));
    document.body.classList.add("no-select");
  }
  if (window.screen?.isExtended) push({ kind: "multi_screen" });

  // Extensions switched on after the lobby check, for the report.
  const seen = new Set(detectExtensions());
  const watch = new MutationObserver(() => {
    for (const name of detectExtensions()) if (!seen.has(name)) { seen.add(name); push({ kind: "extension", detail: name.slice(0, 120) }); }
  });
  watch.observe(document.documentElement, { childList: true, subtree: false, attributes: true });
  watch.observe(document.body, { childList: true });

  const timer = setInterval(() => flush(), 8000);
  return () => { clearInterval(timer); watch.disconnect(); back(); flush(true); off.forEach((f) => f()); document.body.classList.remove("no-select"); };
}

export async function enterFullscreen() {
  try { await document.documentElement.requestFullscreen?.(); } catch { /* some browsers and phones refuse */ }
  return !!document.fullscreenElement;
}
