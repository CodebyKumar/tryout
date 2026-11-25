// TryOut recruiter app. Routes (in the URL hash, so reload and back work):
// #/ roles, #/new, #/role/ID[/candidates/FILTER | /plan | /scoring | /settings], #/role/ID/compare/ID,ID,
// #/report/ID[/evidence | /transcript | /resume | /integrity | /trace | /rating]
import { me } from "../lib/api.js";
import { topBar } from "../lib/shell.js";
import { $, esc } from "../lib/ui.js";
import { comparePage, reportPage } from "./report.js";
import { newRole, rolesPage } from "./roles.js";
import { ROLE_TABS, rolePage } from "./role.js";
import { app, nextNav, stale, state, stopRefresh } from "./store.js";

// What a visitor is looking at on each demo page, and where to go next. Shown above the page.
const DEMO_GUIDE = {
  roles: "This read-only demo holds one role with one finished interview, run by the real AI with a simulated candidate. Open the role to see its candidates.",
  candidates: "Each row is a candidate: where their interview is, the score out of 10 and what the AI suggests. Open the candidate's report, or check the Interview plan and Scoring tabs to see what the AI was told to find out.",
  plan: "The interview plan the AI wrote from the job description: timed parts, the opening question of each, and what the interviewer must find out before moving on.",
  scoring: "The rubric reports are scored against. Each criterion has a weight and a description of below, meets and above the bar.",
  settings: "The role's details and the job description the plan was built from. In your own account you can change them here.",
  report: "Start with Evidence: each score rests on the highlighted quotes; click a time to see it in the transcript. How it decided shows what the AI proposed on every turn and what code changed.",
  compare: "Candidates side by side, criterion by criterion, with each one's strongest quote.",
};
const PENDING = "Your account is waiting for the admin's approval. You can look around now; creating roles and inviting candidates open once it's approved.";

function guide(key) {
  const el = $("#guide");
  const text = state.account.status === "demo" ? DEMO_GUIDE[key] : state.account.status === "pending" ? PENDING : "";
  el.hidden = !text;
  el.innerHTML = text ? `<div class="guide-in"><span class="guide-tag">${state.account.status === "demo" ? "Demo" : "Pending"}</span><p>${esc(text)}</p>${state.account.status === "demo" ? `<a class="btn" href="/signup">Create your account</a>` : ""}</div>` : "";
}

async function route() {
  stopRefresh();
  const nav = nextNav();
  const [, page, id, sub, arg] = location.hash.split("/");
  app.setAttribute("aria-busy", "true");
  const slow = setTimeout(() => !stale(nav) && (app.innerHTML = `<div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`), 150);
  try {
    if (page === "new") { guide("roles"); return await newRole(nav); }
    if (page === "role" && sub === "compare") { guide("compare"); return await comparePage(id, (arg || "").split(",").filter(Boolean), nav); }
    if (page === "role") {
      const tab = ROLE_TABS.some(([k]) => k === sub) ? sub : "candidates";
      guide(tab);
      return await rolePage(id, tab, arg || "all", nav);
    }
    if (page === "report") { guide("report"); return await reportPage(id, sub, nav); }
    guide("roles");
    return await rolesPage(nav);
  } catch (e) {
    if (!stale(nav)) app.innerHTML = `<div class="empty"><h2>Couldn't load this page</h2><p>${esc(e.message)}</p><div class="row"><button type="button" class="btn" onclick="location.reload()">Try again</button></div></div>`;
  } finally { clearTimeout(slow); app.removeAttribute("aria-busy"); }
}

state.account = await me();
if (!state.account) location.href = `/login?next=${encodeURIComponent("/app" + location.hash)}`;
else {
  topBar(state.account);
  window.addEventListener("hashchange", route);
  route();
}
