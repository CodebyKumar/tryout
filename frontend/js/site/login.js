// Sign in (/login) and create account (/signup): one form, two modes. After success, back to where the person was
// going (?next=), else the workspace.
import { api, me } from "../lib/api.js";
import { $, LOGO, status } from "../lib/ui.js";

document.querySelectorAll("[data-brand]").forEach((b) => (b.innerHTML = `${LOGO}<span>TryOut</span>`));
const signUp = location.pathname === "/signup";
const next = new URLSearchParams(location.search).get("next");
const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/app"; // never redirect off-site

if (await me()) location.replace(target);

document.title = `${signUp ? "Create account" : "Sign in"} - TryOut`;
$("#title").textContent = signUp ? "Create your account" : "Sign in";
$("#intro").textContent = signUp
  ? "New accounts can look around at once. Creating roles and inviting candidates opens after the admin approves the account."
  : "Use the email and password you signed up with.";
$("#nameField").hidden = !signUp;
$("#pwHint").hidden = !signUp;
$("[name=password]").autocomplete = signUp ? "new-password" : "current-password";
$("#submit").textContent = signUp ? "Create account" : "Sign in";
$("#switch").innerHTML = signUp
  ? `Already have an account? <a href="/login${location.search}">Sign in</a>`
  : `New to TryOut? <a href="/signup${location.search}">Create an account</a>`;

$("#form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { email: f.get("email").trim(), password: f.get("password") };
  if (signUp) body.name = f.get("name").trim();
  if (signUp && !body.name) return status($("#status"), "Enter your name.", true);
  if (!body.email || !body.password) return status($("#status"), "Enter your email and password.", true);
  $("#submit").disabled = true;
  status($("#status"), signUp ? "Creating your account..." : "Signing in...");
  try {
    await api(signUp ? "/auth/signup" : "/auth/login", { method: "POST", body });
    location.href = target;
  } catch (err) {
    status($("#status"), err.message, true);
    $("#submit").disabled = false;
  }
});
