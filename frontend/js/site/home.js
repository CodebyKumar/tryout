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

// The exchange plays once on load (CSS); Play again restarts it by re-adding the class on the next frame.
$("#replay").addEventListener("click", () => {
  const ex = $("#exchange");
  ex.classList.remove("play");
  requestAnimationFrame(() => requestAnimationFrame(() => ex.classList.add("play")));
});
$("#exchange").classList.add("play");

const account = await me();
if (account) {
  $("#signIn").remove();
  $("#signUp").textContent = "Open workspace";
  $("#signUp").href = "/app";
}
