// Home page: the logo, "Open workspace" when already signed in, the demo buttons, and replaying the exchange.
import { api, me } from "../lib/api.js";
import { $, $$, LOGO } from "../lib/ui.js";

$$("[data-brand]").forEach((b) => (b.innerHTML = `${LOGO}<span>TryOut</span>`));

async function openDemo(e) {
  $$("[data-demo]").forEach((b) => (b.disabled = true));
  $(".demo-status").textContent = "Opening the demo...";
  try { await api("/auth/demo", { method: "POST" }); location.href = "/app"; }
  catch (err) {
    $(".demo-status").textContent = err.message;
    $$("[data-demo]").forEach((b) => (b.disabled = false));
    e.target.focus();
  }
}
$$("[data-demo]").forEach((b) => b.addEventListener("click", openDemo));

// The exchange plays once, when its score row comes into view (on a phone that is below the fold), so the sweep and
// the score are seen rather than finished off-screen. Play again restarts it by re-adding the class on the next frame.
const ex = $("#exchange");
const play = () => { ex.classList.remove("play"); requestAnimationFrame(() => requestAnimationFrame(() => ex.classList.add("play"))); };
$("#replay").addEventListener("click", play);
// Before it plays, hold the panel empty (no highlight, no score), so the visitor never sees the evidence vanish and
// redraw. Without JavaScript, or with reduced motion, the finished state stays as written.
if (!matchMedia("(prefers-reduced-motion: reduce)").matches) ex.classList.add("armed");
const seen = new IntersectionObserver(([entry]) => {
  if (entry.isIntersecting) { seen.disconnect(); play(); }
}, { threshold: 0.9 });
seen.observe($(".ex-score"));

const account = await me();
if (account) {
  $("#signIn").remove();
  $("#signUp").textContent = "Open workspace";
  $("#signUp").href = "/app";
}
