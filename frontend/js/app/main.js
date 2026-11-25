// TryOut recruiter app. Routes (in the URL hash, so reload and back work):
// #/ roles · #/new · #/role/ID[/candidates/FILTER | /plan | /scoring | /settings] · #/role/ID/compare/ID,ID
// · #/report/ID[/evidence | /transcript | /resume | /integrity | /trace | /rating]
import { api, me } from "../lib/api.js";
import { $, brand, esc } from "../lib/ui.js";
import { comparePage, reportPage } from "./report.js";
import { newRole, rolesPage } from "./roles.js";
import { ROLE_TABS, rolePage } from "./role.js";
import { app, nextNav, stale, state, stopRefresh } from "./store.js";

const NOTICE = {
  pending: "Your account is waiting for approval. You can look around; creating roles and inviting candidates open once the admin approves it.",
  demo: "This is the read-only demo: a real interview the AI ran with a simulated candidate. Create an account to run your own.",
};

async function route() {
  stopRefresh();
  const nav = nextNav();
  const [, page, id, sub, arg] = location.hash.split("/");
  app.setAttribute("aria-busy", "true");
  const slow = setTimeout(() => !stale(nav) && (app.innerHTML = `<div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`), 150);
  try {
    if (page === "new") return await newRole(nav);
    if (page === "role" && sub === "compare") return await comparePage(id, (arg || "").split(",").filter(Boolean), nav);
    if (page === "role") return await rolePage(id, ROLE_TABS.some(([k]) => k === sub) ? sub : "candidates", arg || "all", nav);
    if (page === "report") return await reportPage(id, sub, nav);
    return await rolesPage(nav);
  } catch (e) {
    if (!stale(nav)) app.innerHTML = `<div class="empty"><h2>Couldn't load this page</h2><p>${esc(e.message)}</p><div class="row"><button type="button" class="btn" onclick="location.reload()">Try again</button></div></div>`;
  } finally { clearTimeout(slow); app.removeAttribute("aria-busy"); }
}

function shell(account) {
  $("#brand").innerHTML = brand("#/");
  $("#adminLink").hidden = !account.is_admin;
  $("#who").innerHTML = `<span class="name">${esc(account.name)}</span><span class="sub">${esc(account.email)}</span>`;
  const note = NOTICE[account.status];
  $("#notice").hidden = !note;
  $("#notice").innerHTML = note ? `<p>${esc(note)}</p>${account.status === "demo" ? `<a class="btn" href="/signup">Create account</a>` : ""}` : "";
  $("#signOut").addEventListener("click", async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    location.href = "/";
  });
}

state.account = await me();
if (!state.account) location.href = `/login?next=${encodeURIComponent("/app" + location.hash)}`;
else {
  shell(state.account);
  window.addEventListener("hashchange", route);
  route();
}
