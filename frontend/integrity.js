// Browser integrity signals for the interview room, in the spirit of HackerEarth's Smart Browser and HackerRank's
// Proctor Mode: tab switches, window focus loss, leaving full screen, copy and paste, a second screen.
// They are sent to the recruiter as context. They are never scored, and the pasted text itself is never sent.
const MIN_AWAY_SEC = 1.5; // shorter blips (a notification, an alt-tab slip) are not worth a line in a report

export function startMonitor({ clock, send, notify }) {
  let queue = [], away = null, timer = null;
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

  const on = (target, name, fn) => { target.addEventListener(name, fn); return () => target.removeEventListener(name, fn); };
  const off = [
    on(document, "visibilitychange", () => (document.hidden ? leave("tab_hidden") : back())),
    on(window, "blur", () => leave("window_blur")),
    on(window, "focus", () => !document.hidden && back()),
    on(document, "fullscreenchange", () => {
      if (!document.fullscreenElement) leave("fullscreen_exit"); else if (away?.kind === "fullscreen_exit") back();
    }),
    on(document, "copy", () => push({ kind: "copy" })),
    on(document, "paste", (e) => push({ kind: "paste", detail: `${(e.clipboardData?.getData("text") || "").length} characters` })),
    on(window, "pagehide", () => { back(); flush(true); }),
  ];
  if (window.screen?.isExtended) push({ kind: "multi_screen" });
  timer = setInterval(() => flush(), 8000);

  return () => { clearInterval(timer); back(); flush(true); off.forEach((f) => f()); };
}

export async function enterFullscreen() {
  try { await document.documentElement.requestFullscreen?.(); } catch { /* optional: some browsers and phones refuse */ }
}
