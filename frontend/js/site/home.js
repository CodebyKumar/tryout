// Home page: the logo, "Open workspace" when already signed in, and the demo button.
import { api, me } from "../lib/api.js";
import { $, LOGO } from "../lib/ui.js";

document.querySelectorAll("[data-brand]").forEach((b) => (b.innerHTML = `${LOGO}<span>TryOut</span>`));

const account = await me();
if (account) {
  $("#signIn").remove();
  $("#signUp").textContent = "Open workspace";
  $("#signUp").href = "/app";
}

$("#demo").addEventListener("click", async (e) => {
  e.target.disabled = true;
  $("#demoStatus").textContent = "Opening the demo...";
  try { await api("/auth/demo", { method: "POST" }); location.href = "/app"; }
  catch (err) { $("#demoStatus").textContent = err.message; e.target.disabled = false; }
});
