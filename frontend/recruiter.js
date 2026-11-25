// TryOut recruiter app. Routes: #/ roles · #/new · #/role/ID[/candidates/FILTER | /plan | /scoring | /settings]
// · #/role/ID/compare/ID,ID · #/report/ID[/evidence | /transcript | /resume | /integrity | /feedback]
import { $, api, confirmDialog, esc, fmt, postForm, status, ticking } from "/static/common.js";

const app = $("#app");
const RATING = { above_bar: ["Above the bar", "above"], meets_bar: ["Meets the bar", "meets"], below_bar: ["Below the bar", "below"], not_assessed: ["Not assessed", ""] };
const REC = { advance: "Advance", hold: "Hold", reject: "Reject" };
const DECIDED = ["advanced", "hold", "rejected"];
const DECISION = { advanced: "Advanced", hold: "On hold", rejected: "Rejected" };
const FILTERS = [
  ["all", "All", () => true],
  ["invited", "Invited", (c) => c.status === "invited"],
  ["live", "Interviewing", (c) => c.status === "in_progress" || c.evaluating],
  ["review", "To review", (c) => c.status === "completed" && !c.evaluating],
  ["decided", "Decided", (c) => DECIDED.includes(c.status)],
];
const TABS = [["candidates", "Candidates"], ["plan", "Interview plan"], ["scoring", "Scoring"], ["settings", "Settings"]];
const LENGTHS = [5, 10, 15, 20, 30, 45];
let poll = null;
// Every navigation gets a number. A page that finishes loading after you've moved on (slow network, background
// refresh) sees a newer number and doesn't paint over the page you're on.
let navSeq = 0;
const stale = (nav) => nav !== navSeq;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const minutes = (sec) => Math.round(sec / 60);
const skeleton = `<div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`;
const linkFor = (c) => `${location.origin}/i/${c.token}`;

// Reads come from a cache first, so moving between pages and tabs is instant; each read also asks the server again in
// the background and redraws the page only if the answer changed. Every write clears the cache.
const cache = new Map();
async function get(path, redraw) {
  if (!cache.has(path)) { cache.set(path, await api(path)); return cache.get(path); }
  api(path).then((fresh) => {
    const changed = JSON.stringify(fresh) !== JSON.stringify(cache.get(path));
    cache.set(path, fresh);
    if (changed) redraw?.();
  }).catch(() => {});
  return cache.get(path);
}
const send = (path, opts, ms) => api(path, opts, ms).finally(() => cache.clear());

async function route() {
  clearInterval(poll);
  const nav = ++navSeq;
  const [, page, id, sub, arg] = location.hash.split("/");
  app.setAttribute("aria-busy", "true");
  const slow = setTimeout(() => !stale(nav) && (app.innerHTML = skeleton), 150); // only when nothing is cached
  try {
    if (page === "new") return await newRole(nav);
    if (page === "role" && sub === "compare") return await comparePage(id, (arg || "").split(",").filter(Boolean), nav);
    if (page === "role") return await rolePage(id, TABS.some(([k]) => k === sub) ? sub : "candidates", arg || "all", nav);
    if (page === "report") return await reportPage(id, sub, nav);
    return await rolesPage(nav);
  } catch (e) {
    if (!stale(nav)) app.innerHTML = `<div class="empty"><h2>Couldn't load this page</h2><p>${esc(e.message)}</p><div class="row"><button type="button" class="btn" onclick="location.reload()">Try again</button></div></div>`;
  } finally { clearTimeout(slow); app.removeAttribute("aria-busy"); }
}

function refreshLater(fn, nav, ms = 5000) { clearInterval(poll); poll = setInterval(() => !stale(nav) && fn().catch(() => {}), ms); }

// ---------- shell: breadcrumbs and the sidebar's role list ----------
const ICON = {
  back: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  down: `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

// Breadcrumbs, plus a Back button to the parent page on every page below Roles.
function crumbs(items) {
  const parent = items.at(-2);
  $("#back").innerHTML = parent ? `<a class="btn icon back" href="${parent[1]}" aria-label="Back to ${esc(parent[0])}" title="Back to ${esc(parent[0])}">${ICON.back}</a>` : "";
  $("#crumbs").innerHTML = items.map(([label, href], i) => i === items.length - 1
    ? `<span aria-current="page">${esc(label)}</span>`
    : `<a href="${href}">${esc(label)}</a><span class="sep" aria-hidden="true">/</span>`).join("");
}


// Row action menus: one open at a time; an outside click, Escape or picking an item closes it.
function closeMenus() { document.querySelectorAll("[data-menu][aria-expanded=true]").forEach((b) => { b.setAttribute("aria-expanded", "false"); b.nextElementSibling.hidden = true; }); }
function openMenu(btn) {
  const wasOpen = btn.getAttribute("aria-expanded") === "true";
  closeMenus();
  if (wasOpen) return;
  btn.setAttribute("aria-expanded", "true");
  btn.nextElementSibling.hidden = false;
  btn.nextElementSibling.querySelector("[role^=menuitem]")?.focus();
}
document.addEventListener("click", (e) => { if (!e.target.closest(".menu") || e.target.closest("[role^=menuitem]")) closeMenus(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.querySelector("[data-menu][aria-expanded=true]")) { const b = document.querySelector("[data-menu][aria-expanded=true]"); closeMenus(); b.focus(); } });

function wireRows(root = app) { root.querySelectorAll("tr[data-href]").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("button, a, input, .more")) location.hash = tr.dataset.href; })); }
function wireCopy(root = app) {
  root.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    const label = b.textContent;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; setTimeout(() => (b.textContent = label), 1500); }
    catch { prompt("Interview link", b.dataset.copy); }
  }));
}

// ---------- Roles (home) ----------
async function rolesPage(nav) {
  const roles = await get("/roles", () => !stale(nav) && rolesPage(nav));
  if (stale(nav)) return;
  crumbs([["Roles"]]);
  const head = `<div class="page-head"><h1>Roles</h1>
    <div class="actions"><a class="btn primary" href="#/new">Create role</a></div></div>`;
  if (!roles.length) {
    app.innerHTML = `${head}<div class="empty"><h2>No roles yet</h2><p>Create a role from a job description or a template.</p></div>`;
    return;
  }
  const date = (iso) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  app.innerHTML = `${head}<div class="table-wrap"><table class="table"><thead><tr><th>Role</th><th class="num">Candidates</th><th class="num">Interviewed</th><th class="num">To review</th><th class="num">Length</th><th class="num">Brief</th><th class="end">Created</th></tr></thead><tbody>
    ${roles.map((r) => `<tr class="click" data-href="#/role/${r.role_id}"><td><a class="name" href="#/role/${r.role_id}">${esc(r.title)}</a>${r.company ? `<div class="sub">${esc(r.company)}</div>` : ""}</td>
      <td class="num">${r.candidates}</td><td class="num">${r.completed}</td>
      <td class="num">${r.to_review ? `<span class="pill review">${r.to_review}</span>` : "0"}</td>
      <td class="num">${minutes(r.time_budget_sec)} min</td><td class="num">v${r.version}</td><td class="end muted">${date(r.created_at)}</td></tr>`).join("")}</tbody></table></div>`;
  wireRows();
}

// ---------- Create role: one document in, a full interview plan out ----------
async function newRole(nav) {
  crumbs([["Roles", "#/"], ["Create role"]]);
  app.innerHTML = `<div class="page-head"><div><h1>Create role</h1>
    </div></div>
    <div class="create">
      <div class="panel form">
        <label>Job description or hiring notes<textarea id="text" rows="14" placeholder="Paste the job description and anything the interviewer should know: must-haves, red flags, topics to avoid."></textarea></label>
        <div class="upload"><span>Or upload a file</span><button class="btn" type="button" id="pickFile">Choose PDF, Word or text</button><span id="fileName"></span><input type="file" id="file" accept=".pdf,.docx,.txt,.md" class="hidden"></div>
        <div class="fields">
          <label>Role title<input id="title" autocomplete="off" placeholder="Read from the document if empty"></label>
          <label>Interview length<select id="len"><option value="0">As the document says (15 min if not stated)</option>${LENGTHS.map((m) => `<option value="${m * 60}">${m} minutes</option>`).join("")}</select></label>
        </div>
        <div class="row end"><span id="st" class="status" role="status"></span><button id="build" type="button" class="btn primary">Build interview plan</button></div>
      </div>
      <aside class="panel" id="tpl-panel"><div class="panel-title"><h2>Templates</h2></div><div class="tpl-list" id="tpls">${skeleton}</div></aside>
    </div>`;
  const file = $("#file");
  const showFile = () => ($("#fileName").textContent = file.files[0]?.name || "");
  api("/templates").then((list) => {
    if (stale(nav)) return;
    $("#tpls").innerHTML = list.map((t) => `<button class="tpl" type="button" data-tpl="${t.id}"><b>${esc(t.title)}</b><span>${esc(t.summary)}</span></button>`).join("");
    $("#tpls").addEventListener("click", (e) => {
      const t = list.find((x) => x.id === e.target.closest("[data-tpl]")?.dataset.tpl);
      if (!t) return;
      $("#text").value = t.jd; $("#title").value = t.title.replace(/\s*\(.*\)$/, ""); file.value = ""; showFile();
      app.querySelectorAll(".tpl").forEach((b) => b.classList.toggle("sel", b.dataset.tpl === t.id));
    });
  }).catch(() => $("#tpl-panel")?.remove());
  $("#pickFile").addEventListener("click", () => file.click());
  file.addEventListener("change", showFile);
  $("#build").addEventListener("click", async (e) => {
    const fd = new FormData();
    if (file.files[0]) fd.append("file", file.files[0]); else fd.append("text", $("#text").value);
    fd.append("title", $("#title").value.trim());
    fd.append("time_budget_sec", $("#len").value);
    e.target.disabled = true;
    const stop = ticking($("#st"), "Reading the document and designing the interview. Usually under 10 seconds.");
    try { const role = await postForm("/roles/from-document", fd); stop(); location.hash = `#/role/${role.role_id}/plan`; }
    catch (err) { stop(); status($("#st"), err.message, true); e.target.disabled = false; }
  });
}

// ---------- Role: header, tabs, one body per tab ----------
async function rolePage(id, tab, filter, nav = navSeq) {
  const role = await get(`/roles/${id}`, () => !stale(nav) && rolePage(id, tab, filter, nav));
  if (stale(nav)) return;
  crumbs([["Roles", "#/"], [role.title, `#/role/${id}`], [TABS.find(([k]) => k === tab)[1]]]);
  const tabHref = (k) => k === "candidates" ? `#/role/${id}` : `#/role/${id}/${k}`;
  const count = (test) => role.candidates.filter(test).length;
  app.innerHTML = `<div class="page-head"><div><h1>${esc(role.title)}</h1>${role.company ? `<p class="sub">${esc(role.company)}</p>` : ""}</div>
      <div class="actions"><button type="button" class="btn" id="aiBtn">Edit with AI</button><button type="button" class="btn primary" id="addBtn">Add candidates</button></div></div>
    <dl class="stats">
      <div><dt>Candidates</dt><dd><span class="fig">${role.candidates.length}</span></dd></div>
      <div><dt>Interviewed</dt><dd><span class="fig">${count((c) => !["invited", "in_progress"].includes(c.status))}</span></dd></div>
      <div><dt>To review</dt><dd><span class="fig">${count((c) => c.status === "completed")}</span></dd></div>
      <div><dt>Interview length</dt><dd><span class="fig">${minutes(role.time_budget_sec)}</span><span class="unit"> min</span></dd></div>
      <div><dt>Brief version</dt><dd><span class="fig">v${role.version}</span></dd></div>
    </dl>
    <nav class="tabs" aria-label="Role">${TABS.map(([k, label]) => `<a href="${tabHref(k)}" class="${tab === k ? "on" : ""}" ${tab === k ? 'aria-current="page"' : ""}>${label}${k === "candidates" ? `<span class="count">${role.candidates.length}</span>` : ""}</a>`).join("")}</nav>
    <div id="body"></div>`;
  $("#addBtn").addEventListener("click", () => addDialog(role));
  $("#aiBtn").addEventListener("click", () => refineDialog(role));
  const reload = () => rolePage(id, tab, filter);
  if (tab === "plan") return planTab(role, reload);
  if (tab === "scoring") return scoringTab(role, reload);
  if (tab === "settings") return settingsTab(role, reload);
  candidatesTab(role, filter, nav);
}

// A brief change makes a new version; candidates already prepared keep the one they got.
function versionWarning(role) {
  const prepared = role.candidates.filter((c) => c.brief_version).length;
  return prepared ? `<div class="banner warn">${plural(prepared, "candidate")} already prepared on brief v${role.version}. Saving creates v${role.version + 1} for new candidates. Prepared ones keep theirs.</div>` : "";
}

// ---------- Candidates tab ----------
function statusCell(c) {
  if (c.prep_status === "failed" && c.status === "invited") return `<span class="pill failed">Resume read failed</span> <button type="button" class="btn quiet" data-prep="${c.candidate_id}">Retry</button>`;
  if (c.evaluating) return `<span class="pill live">Scoring</span>`;
  if (c.eval_failed) return `<span class="pill failed">Scoring failed</span>`;
  if (DECISION[c.status]) return `<span class="pill ${c.status}">${DECISION[c.status]}</span>`;
  if (c.status === "completed") return `<span class="pill review">Ready for review</span>`;
  if (c.status === "in_progress") return `<span class="pill live">Interviewing</span>`;
  return `<span class="pill">Invited</span>`;
}

function candidatesTab(role, filter, nav) {
  const body = $("#body");
  if (!role.candidates.length) {
    body.innerHTML = `<div class="empty"><h2>No candidates yet</h2><p>Add candidates to get their private interview links.</p>
      <div class="row"><button type="button" class="btn" id="emptyAdd">Add candidates</button><a class="btn quiet" href="#/role/${role.role_id}/plan">Check the interview plan first</a></div></div>`;
    $("#emptyAdd").addEventListener("click", () => addDialog(role));
    return;
  }
  const [, , test] = FILTERS.find(([k]) => k === filter) || FILTERS[0];
  const list = role.candidates.filter(test);
  const canOpen = (c) => c.fit != null || c.score != null || c.status !== "invited";
  body.innerHTML = `<div class="toolbar"><nav class="filters" aria-label="Filter candidates">${FILTERS.map(([k, label, t]) => `<a href="#/role/${role.role_id}/candidates/${k}" class="${k === filter ? "on" : ""}" ${k === filter ? 'aria-current="true"' : ""}>${label}<span class="count">${role.candidates.filter(t).length}</span></a>`).join("")}</nav></div>
    ${list.length ? `<div class="table-wrap"><table class="table"><thead><tr><th class="check"><span class="visually-hidden">Compare</span></th><th>Candidate</th><th>Status</th><th class="num">Score</th><th>AI suggests</th><th class="num">Resume fit</th><th class="num">Brief</th><th class="end"><span class="visually-hidden">Actions</span></th></tr></thead><tbody>
      ${list.map((c) => `<tr ${canOpen(c) ? `class="click" data-href="#/report/${c.candidate_id}"` : ""}>
        <td class="check">${c.score != null ? `<input type="checkbox" data-pick="${c.candidate_id}" aria-label="Compare ${esc(c.name)}">` : ""}</td>
        <td>${canOpen(c) ? `<a class="name" href="#/report/${c.candidate_id}">${esc(c.name)}</a>` : `<span class="name">${esc(c.name)}</span>`}${c.email ? `<div class="sub">${esc(c.email)}</div>` : ""}</td>
        <td>${statusCell(c)}</td>
        <td class="num">${c.score != null ? `${c.score}<span class="muted"> / 10</span>` : `<span class="muted">-</span>`}</td>
        <td>${c.recommendation ? `<span class="pill ${c.recommendation}">${REC[c.recommendation]}</span>` : `<span class="muted">-</span>`}</td>
        <td class="num">${c.fit != null ? `${c.fit}%` : `<span class="muted">-</span>`}</td>
        <td class="num">${c.brief_version ? `v${c.brief_version}` : `<span class="muted">-</span>`}</td>
        <td class="end"><button type="button" class="btn quiet" data-copy="${esc(linkFor(c))}">Copy link</button>
          <div class="more"><button type="button" class="btn quiet icon" data-menu aria-haspopup="menu" aria-expanded="false" aria-label="More actions for ${esc(c.name)}">&hellip;</button><div class="menu" role="menu" hidden>
            ${canOpen(c) ? `<a class="btn quiet" role="menuitem" href="#/report/${c.candidate_id}">Open report</a>` : ""}
            ${canOpen(c) ? `<button type="button" class="btn quiet" role="menuitem" data-reset="${c.candidate_id}">Reset interview</button>` : ""}
            <button type="button" class="btn quiet danger" role="menuitem" data-delete="${c.candidate_id}" data-name="${esc(c.name)}">Delete candidate</button></div></div></td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty"><h2>Nobody here</h2><p>No candidates match this filter.</p></div>`}
    <div class="pickbar hidden" id="pickbar" role="region" aria-label="Compare"><span id="pickCount"></span><a class="btn primary" id="compare" href="#">Compare</a></div>`;

  const reload = () => rolePage(role.role_id, "candidates", filter);
  const bar = $("#pickbar"), cmp = $("#compare");
  body.querySelectorAll("[data-pick]").forEach((box) => box.addEventListener("change", () => {
    const ids = [...body.querySelectorAll("[data-pick]:checked")].map((x) => x.dataset.pick);
    if (ids.length > 4) { box.checked = false; ids.pop(); }
    bar.classList.toggle("hidden", !ids.length);
    $("#pickCount").textContent = ids.length < 2 ? "Select one more scored candidate to compare" : `${ids.length} selected`;
    cmp.href = `#/role/${role.role_id}/compare/${ids.join(",")}`;
    cmp.setAttribute("aria-disabled", ids.length < 2);
  }));
  wireRows(body); wireCopy(body);
  body.querySelectorAll("[data-menu]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openMenu(b); }));
  body.querySelectorAll("[data-prep]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true; b.textContent = "Reading...";
    try { await send(`/candidates/${b.dataset.prep}/prepare`, { method: "POST" }); reload(); }
    catch (err) { b.disabled = false; b.title = err.message; b.textContent = "Still failing, retry"; }
  }));
  body.querySelectorAll("[data-reset]").forEach((b) => b.addEventListener("click", async () => {
    if (!await confirmDialog({ title: "Reset this interview?", confirm: "Reset interview",
      body: "The transcript, report, resume and resume fit are cleared. The same link works again, and the candidate uploads their resume again." })) return;
    await send(`/candidates/${b.dataset.reset}/reset`, { method: "POST" });
    reload();
  }));
  body.querySelectorAll("[data-delete]").forEach((b) => b.addEventListener("click", async () => {
    if (!await confirmDialog({ title: `Delete ${b.dataset.name}?`, confirm: "Delete candidate", danger: true,
      body: "Their resume, transcript and report are permanently removed, and the interview link stops working." })) return;
    await send(`/candidates/${b.dataset.delete}`, { method: "DELETE" });
    reload();
  }));
  if (role.candidates.some((c) => c.status === "in_progress" || c.evaluating)) {
    // a refresh redraws the table, so skip it while the recruiter has a row selected or a menu open
    refreshLater(async () => { if (!app.querySelector("[data-pick]:checked, [data-menu][aria-expanded=true]")) await rolePage(role.role_id, "candidates", filter, nav); }, nav);
  }
}

// Add candidates: one row per person (name and email), then their private links. Candidates upload their own resume
// in the lobby, so nothing else is asked here.
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/; // same shape check as the server
function addDialog(role) {
  const dlg = document.createElement("dialog");
  dlg.className = "dialog wide";
  dlg.innerHTML = `<form method="dialog" id="addForm" novalidate><h2>Add candidates</h2>
    <p>Each candidate gets a private interview link.</p>
    <div class="people" role="group" aria-label="Candidates"><div class="people-head" aria-hidden="true"><span>Full name</span><span>Email</span><span></span></div><div id="rows"></div></div>
    <button type="button" class="btn quiet add-row" id="addRow">Add another candidate</button>
    <p id="dst" class="status" role="status"></p>
    <div class="dialog-actions"><button class="btn" type="button" id="cancel">Cancel</button><button class="btn primary" id="create" type="submit">Create link</button></div></form>`;
  document.body.appendChild(dlg);
  const rows = $("#rows", dlg);
  const count = () => rows.children.length;
  const sync = () => {
    rows.querySelectorAll("[data-remove]").forEach((b) => (b.disabled = count() === 1));
    $("#create", dlg).textContent = count() === 1 ? "Create link" : "Create links";
  };
  const addRow = () => {
    const n = ++addRow.seq;
    rows.insertAdjacentHTML("beforeend", `<div class="person">
      <input name="name" autocomplete="off" aria-label="Full name, candidate ${n}" placeholder="Riya Pillai">
      <input name="email" type="email" inputmode="email" autocomplete="off" aria-label="Email, candidate ${n}" placeholder="riya@example.com">
      <button type="button" class="btn quiet icon" data-remove aria-label="Remove candidate ${n}">&times;</button>
      <p class="field-err" aria-live="polite"></p></div>`);
    const row = rows.lastElementChild;
    $("[data-remove]", row).addEventListener("click", () => { row.remove(); sync(); rows.querySelector("input")?.focus(); });
    row.querySelectorAll("input").forEach((i) => i.addEventListener("input", () => { i.removeAttribute("aria-invalid"); $(".field-err", row).textContent = ""; }));
    sync();
    $("input", row).focus();
  };
  addRow.seq = 0;
  addRow();
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.addEventListener("cancel", () => dlg.remove());
  $("#cancel", dlg).addEventListener("click", close);
  $("#addRow", dlg).addEventListener("click", addRow);

  // Checks every row before sending anything: a name, a valid email, no email twice. Marks each problem in place.
  const check = () => {
    const seen = new Set(), people = [];
    for (const row of [...rows.children]) {
      const [name, email] = [...row.querySelectorAll("input")];
      const v = { name: name.value.trim(), email: email.value.trim().toLowerCase(), row };
      if (!v.name && !v.email && rows.children.length > 1) { row.remove(); continue; } // blank extra row: ignore it
      const err = !v.name ? [name, "Enter a name."] : !EMAIL.test(v.email) ? [email, "Enter a valid email, like name@example.com."]
        : seen.has(v.email) ? [email, "This email is already in the list."] : null;
      seen.add(v.email);
      if (err) { err[0].setAttribute("aria-invalid", "true"); $(".field-err", row).textContent = err[1]; }
      else people.push(v);
    }
    sync();
    const bad = rows.querySelector("[aria-invalid]");
    bad?.focus();
    return bad ? null : people;
  };

  $("#addForm", dlg).addEventListener("submit", async (e) => {
    e.preventDefault();
    const people = check();
    if (!people) return status($("#dst", dlg), "Fix the highlighted fields.", true);
    $("#create", dlg).disabled = true;
    const made = [];
    for (const [i, p] of people.entries()) {
      status($("#dst", dlg), `Creating ${i + 1} of ${people.length}...`);
      try { made.push(await send(`/roles/${role.role_id}/candidates`, { method: "POST", body: { name: p.name, email: p.email } })); p.row.remove(); }
      catch (err) { $(".field-err", p.row).textContent = err.message; $('[name="email"]', p.row).setAttribute("aria-invalid", "true"); }
    }
    if (count()) { // some rows failed: keep them for fixing, say what was created
      status($("#dst", dlg), `${made.length ? `${plural(made.length, "link")} created. ` : ""}Fix the rows that are left and try again.`, true);
      $("#create", dlg).disabled = false; sync();
      if (!made.length) return;
      return dlg.addEventListener("close", () => route(), { once: true });
    }
    const links = made.map((c) => `${c.name}: ${linkFor(c)}`).join("\n");
    $("#addForm", dlg).innerHTML = `<h2>${plural(made.length, "link")} ready</h2>
      <ul class="links">${made.map((c) => `<li><div><span class="name">${esc(c.name)}</span><div class="hint">${esc(c.email)}</div></div><button type="button" class="btn" data-copy="${esc(linkFor(c))}">Copy link</button></li>`).join("")}</ul>
      <div class="dialog-actions">${made.length > 1 ? `<button type="button" class="btn" id="copyAll">Copy all links</button>` : ""}<button type="button" class="btn primary" id="done">Done</button></div>`;
    wireCopy(dlg);
    $("#copyAll", dlg)?.addEventListener("click", async (ev) => { try { await navigator.clipboard.writeText(links); ev.target.textContent = "Copied"; } catch { prompt("Links", links); } });
    $("#done", dlg).addEventListener("click", () => { close(); location.hash = `#/role/${role.role_id}`; route(); });
  });
  dlg.showModal();
}

// Plain-language change to the whole brief (sections and scoring) through Role Refine.
function refineDialog(role) {
  const dlg = document.createElement("dialog");
  dlg.className = "dialog wide";
  dlg.innerHTML = `<form method="dialog" id="aiForm"><h2>Edit with AI</h2>
    ${versionWarning(role)}
    <label>What should change<textarea id="ask" rows="4" placeholder="For example: spend more time on system design, drop the logistics question, add a red flag for copy-pasted answers."></textarea></label>
    <p id="ast" class="status" role="status"></p>
    <div class="dialog-actions"><button class="btn" type="button" id="cancel">Cancel</button><button class="btn primary" id="apply" type="submit">Apply change</button></div></form>`;
  document.body.appendChild(dlg);
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.addEventListener("cancel", () => dlg.remove());
  $("#cancel", dlg).addEventListener("click", close);
  $("#aiForm", dlg).addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!$("#ask", dlg).value.trim()) return status($("#ast", dlg), "Describe the change first.", true);
    $("#apply", dlg).disabled = true;
    const stop = ticking($("#ast", dlg), "Updating the brief...");
    try { await send(`/roles/${role.role_id}/refine`, { method: "POST", body: { instruction: $("#ask", dlg).value } }, 90000); stop(); close(); route(); }
    catch (err) { stop(); status($("#ast", dlg), err.message, true); $("#apply", dlg).disabled = false; }
  });
  dlg.showModal();
  $("#ask", dlg).focus();
}

async function save(role, changes, el, reload) {
  try { await send(`/roles/${role.role_id}`, { method: "PUT", body: changes }); reload(); }
  catch (e) { status(el, e.message, true); }
}
const v = (el, k) => el.querySelector(`[data-k="${k}"]`).value;

// ---------- Interview plan tab: the timeline bar, then one ruled row per section ----------
function planTab(role, reload) {
  let t = 0;
  const starts = role.sections.map((s) => { const at = t; t += s.time_budget_sec; return at; });
  const body = $("#body");
  body.innerHTML = `<div class="toolbar"><div><h2>Interview plan</h2>
      <p class="hint">${plural(role.sections.length, "part")}, ${minutes(t)} of ${minutes(role.time_budget_sec)} min</p></div>
      <button type="button" class="btn" id="editPlan">Edit plan</button></div>
    <div class="timebar" aria-hidden="true">${role.sections.map((s) => `<i class="${s.priority === 3 ? "opt" : ""}" style="flex:${s.time_budget_sec}" title="${esc(s.name)}"></i>`).join("")}<i class="opt" style="flex:${Math.max(0, role.time_budget_sec - t)};opacity:.35"></i></div>
    <div id="planBody" style="margin-top:var(--space-lg)"><ol class="plan">${role.sections.map((s, i) => `<li>
      <div class="when"><span class="mono">${fmt(starts[i])}</span><span>${Math.round(s.time_budget_sec / 6) / 10} min</span></div>
      <div><div class="head"><h3>${esc(s.name)}</h3>${s.priority === 3 ? `<span class="pill">Skipped if short on time</span>` : ""}</div>
        <p class="q">“${esc(s.opening_question)}”</p>
        ${s.intent ? `<p class="intent">${esc(s.intent)}</p>` : ""}
        <ul class="slots" aria-label="What the interviewer finds out">${s.slots.map((x) => `<li class="${x.required ? "" : "opt"}">${esc(x.desc)}${x.required ? "" : " (if time allows)"}</li>`).join("")}</ul></div></li>`).join("")}</ol></div>`;
  $("#editPlan").addEventListener("click", (e) => { e.target.remove(); planEditor(role, reload); });
}

function planEditor(role, reload) {
  const slotText = (s) => s.slots.map((x) => `${x.desc}${x.required ? "" : " (optional)"}`).join("\n");
  $("#planBody").innerHTML = `${versionWarning(role)}<div class="panel">${role.sections.map((s, i) => `<div class="edit-block" data-sec="${i}">
      <div class="fields"><label>Part name<input data-k="name" value="${esc(s.name)}"></label><label>Minutes<input data-k="min" type="number" inputmode="decimal" min="0.5" step="0.5" value="${s.time_budget_sec / 60}"></label></div>
      <label>Opening question<input data-k="q" value="${esc(s.opening_question)}"></label>
      <label>Purpose<input data-k="intent" value="${esc(s.intent)}"></label>
      <label>What to find out <span class="hint">One per line. End a line with (optional) if it can be skipped.</span><textarea data-k="slots" rows="${s.slots.length + 1}">${esc(slotText(s))}</textarea></label></div>`).join("")}
    <div class="edit-actions"><span id="est" class="status" role="status"></span><button type="button" class="btn" id="cancelEdit">Cancel</button><button type="button" id="saveEdit" class="btn">Save plan</button></div></div>`;
  $("#cancelEdit").addEventListener("click", reload);
  $("#saveEdit").addEventListener("click", () => {
    const sections = role.sections.map((s, i) => {
      const el = app.querySelector(`[data-sec="${i}"]`);
      const slots = v(el, "slots").split("\n").map((l) => l.trim()).filter(Boolean).map((l, j) => ({
        slot_id: s.slots[j]?.slot_id || `s${j + 1}`, desc: l.replace(/\s*\(optional\)$/i, ""), required: !/\(optional\)$/i.test(l) }));
      return { ...s, name: v(el, "name"), opening_question: v(el, "q"), intent: v(el, "intent"), time_budget_sec: Math.round(+v(el, "min") * 60), slots };
    });
    save(role, { sections }, $("#est"), reload);
  });
}

// ---------- Scoring tab: one disclosure row per criterion ----------
function scoringTab(role, reload) {
  const total = role.criteria.reduce((a, c) => a + c.weight, 0) || 1;
  $("#body").innerHTML = `<div class="toolbar"><div><h2>Scoring</h2>
      <p class="hint">${role.criteria.length} ${role.criteria.length === 1 ? "criterion" : "criteria"}, each scored 1 to 10</p></div>
      <button type="button" class="btn" id="editCrit">Edit scoring</button></div>
    <dl class="rules">
      <div><dt>Criterion score</dt><dd>Below the bar 1 to 4, meets 5 to 7, above 8 to 10. Only ratings backed by a quote count.</dd></div>
      <div><dt>Overall score</dt><dd>Weighted average out of 10, shown once quote-backed criteria cover half the weight.</dd></div>
      <div><dt>AI suggestion</dt><dd>Reject under 5 or a weak key criterion. Advance from 6 with every key criterion backed.</dd></div>
    </dl>
    <div id="critBody">${role.criteria.length ? `<div class="crits">${role.criteria.map((c) => `<details class="crit"><summary>
        <div><h3>${esc(c.name)}</h3>${c.description ? `<p>${esc(c.description)}</p>` : ""}</div>
        <div class="weight"><span><span class="fig">${Math.round((c.weight / total) * 100)}%</span> of score (weight ${c.weight})</span><div class="meter"><div style="width:${(c.weight / total) * 100}%"></div></div></div></summary>
      <div class="bars"><div class="above"><b>Above the bar, 8 to 10</b>${esc(c.above_bar) || "-"}</div><div class="meets"><b>Meets the bar, 5 to 7</b>${esc(c.meets_bar) || "-"}</div><div class="below"><b>Below the bar, 1 to 4</b>${esc(c.below_bar) || "-"}</div></div></details>`).join("")}</div>` : `<div class="empty"><h2>No criteria</h2><p>Use Edit with AI to add scoring criteria.</p></div>`}</div>`;
  $("#editCrit").addEventListener("click", (e) => { e.target.remove(); scoringEditor(role, reload); });
}

function scoringEditor(role, reload) {
  $("#critBody").innerHTML = `${versionWarning(role)}<div class="panel">${role.criteria.map((c, i) => `<div class="edit-block" data-crit="${i}">
      <div class="fields"><label>Criterion<input data-k="name" value="${esc(c.name)}"></label><label>Weight <span class="hint">0.5 to 3</span><input data-k="weight" type="number" inputmode="decimal" min="0.5" max="3" step="0.5" value="${c.weight}"></label></div>
      <label>What it measures<input data-k="description" value="${esc(c.description)}"></label>
      <div class="fields"><label>Above the bar<textarea data-k="above_bar" rows="3">${esc(c.above_bar)}</textarea></label><label>Meets the bar<textarea data-k="meets_bar" rows="3">${esc(c.meets_bar)}</textarea></label><label>Below the bar<textarea data-k="below_bar" rows="3">${esc(c.below_bar)}</textarea></label></div></div>`).join("")}
    <div class="edit-actions"><span id="est" class="status" role="status"></span><button type="button" class="btn" id="cancelEdit">Cancel</button><button type="button" id="saveEdit" class="btn">Save scoring</button></div></div>`;
  $("#cancelEdit").addEventListener("click", reload);
  $("#saveEdit").addEventListener("click", () => {
    const criteria = role.criteria.map((c, i) => {
      const el = app.querySelector(`[data-crit="${i}"]`);
      return { ...c, name: v(el, "name"), weight: +v(el, "weight"), description: v(el, "description"), above_bar: v(el, "above_bar"), meets_bar: v(el, "meets_bar"), below_bar: v(el, "below_bar") };
    });
    save(role, { criteria }, $("#est"), reload);
  });
}

// ---------- Settings tab: role details and the job description it was built from ----------
// Saves only what changed. Title and company are labels; length and notes change the brief, so they make a new version.
function settingsTab(role, reload) {
  const len = minutes(role.time_budget_sec);
  const opts = [...new Set([...LENGTHS, len])].sort((a, b) => a - b);
  const prepared = role.candidates.filter((c) => c.brief_version).length;
  $("#body").innerHTML = `<div class="cols">
    <form class="panel form" id="settings"><div class="panel-title"><h2>Role details</h2></div>
      <div class="fields"><label>Role title<input name="title" required autocomplete="off" value="${esc(role.title)}"></label><label>Company<input name="company" autocomplete="organization" value="${esc(role.company)}"></label></div>
      <label>Interview length<select name="len">${opts.map((m) => `<option value="${m}" ${m === len ? "selected" : ""}>${m} minutes</option>`).join("")}</select></label>
      <label>Notes for the interviewer<textarea name="notes" rows="5" placeholder="Must-haves, red flags, topics to avoid.">${esc(role.notes)}</textarea></label>
      <p class="banner warn hidden" id="newVersion">Saving creates brief v${role.version + 1}.${prepared ? ` ${plural(prepared, "candidate")} already prepared keep v${role.version}.` : ""}</p>
      <div class="row end"><span id="sst" class="status" role="status"></span><button type="submit" class="btn primary" id="saveSettings" disabled>Save changes</button></div></form>
    <section class="panel"><div class="panel-title"><h2>Job description</h2></div><div class="source">${esc(role.jd) || "None saved."}</div></section></div>`;
  const form = $("#settings");
  const changes = () => {
    const f = new FormData(form);
    const now = { title: f.get("title").trim(), company: f.get("company").trim(), notes: f.get("notes"), time_budget_sec: +f.get("len") * 60 };
    return Object.fromEntries(Object.entries(now).filter(([k, v]) => v !== role[k]));
  };
  form.addEventListener("input", () => {
    const c = changes();
    $("#saveSettings").disabled = !Object.keys(c).length;
    $("#newVersion").classList.toggle("hidden", !("notes" in c || "time_budget_sec" in c));
    status($("#sst"), "");
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const c = changes();
    if ("title" in c && !c.title) return status($("#sst"), "The role needs a title.", true);
    $("#saveSettings").disabled = true;
    try { await send(`/roles/${role.role_id}`, { method: "PUT", body: c }); await reload(); status($("#sst"), "Saved"); }
    catch (err) { status($("#sst"), err.message, true); $("#saveSettings").disabled = false; }
  });
}

// ---------- Report: header and decision, stat strip, summary, then one tab per kind of evidence ----------
const MATCH = { strong: ["Clear evidence", "above"], partial: ["Some evidence", "warn"], none: ["Not in resume", "below"] };
const INTEGRITY = {
  tab_hidden: "Switched to another tab", window_blur: "Switched to another window", fullscreen_exit: "Left full screen",
  paste: "Pasted text", copy: "Copied text", multi_screen: "A second screen is connected",
};
const LEVEL = { none: ["No activity noted", ""], some: ["Some activity", "warn"], review: ["Worth a look", "below"] };

function fitPane(fit) {
  if (!fit || fit.score == null) return `<div class="empty"><h2>No resume read</h2><p>The candidate hasn't shared a resume, or it couldn't be read.</p></div>`;
  return `<div class="pane-head"><p>${esc(fit.summary)}</p></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>Requirement</th><th>Type</th><th>Match</th><th>From the resume</th></tr></thead><tbody>
    ${[...fit.items].sort((a, b) => b.must_have - a.must_have).map((i) => `<tr><td>${esc(i.requirement)}</td><td class="muted nowrap">${i.must_have ? "Must-have" : "Nice to have"}</td>
      <td><span class="pill ${MATCH[i.match][1]}">${MATCH[i.match][0]}</span></td><td class="sub">${esc(i.evidence) || "-"}</td></tr>`).join("")}</tbody></table></div>`;
}

// Every browser check the room runs, whether it was triggered, and when. Never scored, never seen by the evaluator.
const CHECKS = [
  [["tab_hidden", "window_blur"], "Left the interview tab or window"], [["fullscreen_exit"], "Left full screen"],
  [["paste"], "Pasted text"], [["copy"], "Copied text"], [["multi_screen"], "Second screen connected"],
];
function integrityPane(g) {
  const rows = CHECKS.map(([kinds, label]) => {
    const hits = g.events.filter((e) => kinds.includes(e.kind));
    const evidence = hits.map((e) => `<li><span class="mono">${fmt(e.at_sec)}</span>${e.seconds ? ` for ${Math.round(e.seconds)}s` : ""}${e.detail ? `, ${esc(e.detail)}` : ""}</li>`).join("");
    return `<tr><td>${label}</td><td>${hits.length ? `<span class="pill warn">${plural(hits.length, "time")}</span>` : `<span class="pill above">Not seen</span>`}</td>
      <td>${hits.length ? `<ul class="evidence">${evidence}</ul>` : `<span class="muted">-</span>`}</td></tr>`;
  }).join("");
  return `<div class="table-wrap"><table class="table"><thead><tr><th>Check</th><th>Result</th><th>When</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

const STARS = ["", "Poor", "Fair", "Good", "Very good", "Excellent"];

// The downloadable report: a paper document built from the same data, not a print of the screen.
function printReport(d, decision) {
  const c = d.candidate, r = d.report, g = d.integrity;
  const total = d.role.criteria.reduce((a, x) => a + x.weight, 0) || 1;
  const weight = (id) => Math.round(((d.role.criteria.find((x) => x.criterion_id === id)?.weight || 0) / total) * 100);
  const flagged = g ? CHECKS.map(([kinds, label]) => [label, g.events.filter((e) => kinds.includes(e.kind))]).filter(([, hits]) => hits.length) : [];
  const date = new Date(r.created_at).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  const items = (title, list) => list.length ? `<div><h3>${title}</h3><ul>${list.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  return `<article class="print-report">
    <header><p class="brand">TryOut</p><h1>${esc(c.name)}</h1><p>${esc(d.role.title)}${c.email ? `, ${esc(c.email)}` : ""}</p><p class="muted">Interview report, ${date}, ${fmt(d.duration_sec)} long</p></header>
    <table class="facts"><tr>
      <td><span>Overall score</span><b>${r.overall_score != null ? `${r.overall_score} / 10` : "Not enough evidence"}</b></td>
      <td><span>AI suggests</span><b>${r.recommendation ? REC[r.recommendation] : "No suggestion"}</b></td>
      <td><span>Decision</span><b>${decision ? DECISION[decision] : "Not decided"}</b></td>
      <td><span>Resume fit</span><b>${d.fit?.score != null ? `${d.fit.score}%` : "-"}</b></td>
    </tr></table>
    <section><h2>Summary</h2><p>${esc(r.summary)}</p>${r.recommendation_reason ? `<p><b>Why the suggestion:</b> ${esc(r.recommendation_reason)}</p>` : ""}</section>
    <section class="two">${items("Strengths", r.strengths)}${items("Concerns", r.concerns)}${items("Resume claims not backed up", r.resume_flags)}</section>
    <section><h2>Scores by criterion</h2><table class="crit-table"><thead><tr><th>Criterion</th><th>Weight</th><th>Rating</th><th>Score</th><th>Evidence from the interview</th></tr></thead><tbody>
      ${r.criteria.map((x) => `<tr><td>${esc(x.name)}</td><td>${weight(x.criterion_id)}%</td><td>${RATING[x.rating][0]}</td><td>${x.score != null && x.verified ? `${x.score} / 10` : "-"}</td>
        <td>${x.evidence.map((e) => `<p>${e.at} “${esc(e.quote)}”</p>`).join("") || `<p class="muted">${x.verified ? "No evidence" : "Not backed by a quote, not counted"}</p>`}</td></tr>`).join("")}</tbody></table></section>
    <section><h2>Integrity</h2>${flagged.length ? `<ul>${flagged.map(([label, hits]) => `<li>${label}: ${hits.map((e) => `${fmt(e.at_sec)}${e.seconds ? ` (${Math.round(e.seconds)}s)` : ""}`).join(", ")}</li>`).join("")}</ul>` : "<p>No issues noted.</p>"}</section>
    ${d.experience ? `<section><h2>Candidate rating of the interview</h2><p>${d.experience.stars} / 5, ${STARS[d.experience.stars]}${d.experience.comment ? `: “${esc(d.experience.comment)}”` : ""}</p></section>` : ""}
  </article>`;
}
function ratingPane(x) {
  if (!x) return `<div class="empty"><h2>Not rated yet</h2><p>Candidates are asked to rate the interview when it ends.</p></div>`;
  return `<div class="rating"><div class="rating-score"><span class="fig">${x.stars}</span><span class="unit"> / 5</span></div>
    <div><p class="rating-word">${STARS[x.stars]}</p><div class="stars" aria-hidden="true">${[1, 2, 3, 4, 5].map((n) => `<i class="${n <= x.stars ? "on" : ""}"></i>`).join("")}</div></div></div>
    ${x.comment ? `<blockquote class="comment">${esc(x.comment)}</blockquote>` : `<p class="muted">No comment left.</p>`}`;
}

function highlight(text, quotes) {
  const low = text.toLowerCase(), ranges = [];
  for (const q of quotes) {
    const needle = q.toLowerCase().replace(/^[\s"'.,]+|[\s"'.,]+$/g, "");
    const i = needle ? low.indexOf(needle) : -1;
    if (i >= 0) ranges.push([i, i + needle.length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  let out = "", pos = 0;
  for (const [a, b] of ranges) { if (a < pos) continue; out += esc(text.slice(pos, a)) + `<mark>${esc(text.slice(a, b))}</mark>`; pos = b; }
  return out + esc(text.slice(pos));
}

async function reportPage(id, tab, nav = navSeq) {
  const d = await get(`/candidates/${id}`, () => !stale(nav) && reportPage(id, tab, nav));
  if (stale(nav)) return;
  const c = d.candidate, r = d.report;
  crumbs([["Roles", "#/"], [d.role.title, `#/role/${c.role_id}`], [c.name]]);
  if (!r) {
    const scoring = d.state === "EVALUATING";
    const note = scoring ? "Scoring the interview. This usually takes under a minute."
      : d.state === "EVAL_FAILED" ? `Scoring failed, the transcript is safe. ${esc(d.eval_error)}`
      : d.state === "DONE" ? "This interview hasn't been scored." : c.status === "in_progress" ? "Interview in progress." : "Hasn't taken the interview yet.";
    app.innerHTML = `<div class="page-head"><div><h1>${esc(c.name)}</h1><p class="sub">${note}</p></div>
      ${d.state === "DONE" || d.state === "EVAL_FAILED" ? `<div class="row"><span id="rst" class="status" role="status"></span><button type="button" id="reeval" class="btn primary">${d.state === "DONE" ? "Score interview" : "Retry scoring"}</button></div>` : ""}</div>
      ${d.fit?.score != null ? `<section class="panel"><div class="panel-title"><h2>Resume fit</h2><span class="fit">${d.fit.score}%</span></div>${fitPane(d.fit)}</section>` : ""}`;
    if (scoring || c.status === "in_progress") refreshLater(() => reportPage(id, tab, nav), nav, 3000);
    $("#reeval")?.addEventListener("click", async (e) => {
      e.target.disabled = true; status($("#rst"), "Scoring...");
      try { await send(`/candidates/${id}/reevaluate`, { method: "POST" }, 90000); reportPage(id, tab); }
      catch (err) { status($("#rst"), err.message, true); e.target.disabled = false; }
    });
    return;
  }
  const quotesByTurn = {};
  r.criteria.forEach((x) => x.evidence.forEach((e) => (quotesByTurn[e.turn_id] ||= []).push(e.quote)));
  const met = r.criteria.filter((x) => x.rating === "above_bar" || x.rating === "meets_bar").length;
  const decision = DECIDED.includes(c.status) ? c.status : null;
  const first = esc(c.name.split(" ")[0]);
  const g = d.integrity;
  const tabs = [
    ["evidence", "Evidence", r.criteria.length],
    ["transcript", "Transcript", d.transcript.length],
    ["resume", "Resume fit", null],
    ...(g ? [["integrity", "Integrity", g.events.length || null]] : []),
    ["rating", "Candidate rating", null],
  ];
  if (!tabs.some(([k]) => k === tab)) tab = "evidence";
  const list = (title, items) => `<div><h3>${title}</h3><ul class="side-list">${items.map((s) => `<li>${esc(s)}</li>`).join("") || "<li class='muted'>None noted</li>"}</ul></div>`;

  app.innerHTML = `<div class="page-head"><h1>${esc(c.name)}</h1>
      <div class="actions"><button type="button" class="btn quiet no-print" id="download">Download</button>
        <div class="more"><button type="button" class="btn ${decision ? "" : "primary"}" data-menu aria-haspopup="menu" aria-expanded="false">${decision ? DECISION[decision] : "Make a decision"}${ICON.down}</button>
          <div class="menu" role="menu" hidden>${[["advanced", "Advance"], ["hold", "Hold"], ["rejected", "Reject"]].map(([k, l]) => `<button type="button" class="btn quiet ${k === "rejected" ? "danger" : ""}" role="menuitemradio" aria-checked="${decision === k}" data-dec="${k}">${l}${decision === k ? " (current)" : ""}</button>`).join("")}</div></div></div></div>

    <dl class="stats">
      <div><dt>Score</dt><dd>${r.overall_score != null ? `<span class="fig">${r.overall_score}</span><span class="unit"> / 10</span>` : `<span class="muted">Not enough evidence</span>`}</dd></div>
      <div><dt>AI suggests</dt><dd>${r.recommendation ? `<span class="pill ${r.recommendation}">${REC[r.recommendation]}</span>` : `<span class="pill">No suggestion</span>`}</dd></div>
      <div><dt>Criteria met</dt><dd><span class="fig">${met}</span><span class="unit"> of ${r.criteria.length}</span></dd></div>
      <div><dt>Resume fit</dt><dd>${d.fit?.score != null ? `<span class="fig">${d.fit.score}</span><span class="unit">%</span>` : `<span class="fig">-</span>`}</dd></div>
      <div><dt>Integrity</dt><dd>${g ? `<span class="pill ${LEVEL[g.level][1]}">${LEVEL[g.level][0]}</span>` : "-"}</dd></div>
    </dl>

    <section class="panel summary"><h2>Summary</h2>
      <p class="memo">${esc(r.summary)}</p>
      ${r.recommendation_reason ? `<p class="reason"><b>Why the suggestion:</b> ${esc(r.recommendation_reason)}</p>` : ""}
      <div class="lists">${list("Strengths", r.strengths)}${list("Concerns", r.concerns)}${r.resume_flags.length ? list("Resume claims not backed up", r.resume_flags) : ""}</div>
      ${d.flags.length ? `<p class="hint">The candidate mentioned personal details (${[...new Set(d.flags.map((f) => f.subtype))].map(esc).join(", ")}). These are never scored.</p>` : ""}
    </section>

    <nav class="tabs" role="tablist" aria-label="Report">${tabs.map(([k, label, n]) => `<a href="#/report/${id}/${k}" role="tab" data-tab="${k}" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}">${label}${n != null ? `<span class="count">${n}</span>` : ""}</a>`).join("")}</nav>

    <section class="pane" data-pane="evidence">
      <div class="ledger">${r.criteria.map((x) => {
        const [label, cls] = RATING[x.rating];
        return `<article class="ledger-row"><div class="lg-score">${x.score ? `<span class="fig">${x.score}</span><span class="small muted">/ 10</span>` : `<span class="muted">-</span>`}</div>
          <div><div class="crit-top"><h3>${esc(x.name)}</h3><span class="pill ${cls}">${label}</span></div>
            <p class="rationale">${esc(x.rationale)}</p>
            ${x.verified ? "" : `<p class="small warn-text">No quote backs this rating, so it doesn't count toward the score.</p>`}
            ${x.evidence.map((e) => `<div class="quote"><a href="#" data-jump="${e.turn_id}" title="Show in the transcript">${e.at}</a><span><mark>${esc(e.quote)}</mark></span></div>`).join("")}</div></article>`;
      }).join("")}</div></section>
    <section class="pane" data-pane="transcript">
      <div class="transcript">${d.transcript.map((t) => `<div class="line ${t.role}" id="t-${t.turn_id}"><span class="t">${t.at}</span><span class="who">${t.role === "user" ? first : "Interviewer"}</span>
        <span class="text">${t.role === "user" ? highlight(t.text, quotesByTurn[t.turn_id] || []) : esc(t.text)}</span></div>`).join("")}</div></section>
    <section class="pane" data-pane="resume">${fitPane(d.fit)}</section>
    ${g ? `<section class="pane" data-pane="integrity">${integrityPane(g)}</section>` : ""}
    <section class="pane" data-pane="rating">${ratingPane(d.experience)}</section>
    ${printReport(d, decision)}`;

  // Tabs switch in place; the URL keeps the tab without a reload.
  const select = (k) => {
    app.querySelectorAll("[data-tab]").forEach((a) => { a.classList.toggle("on", a.dataset.tab === k); a.setAttribute("aria-selected", a.dataset.tab === k); });
    app.querySelectorAll("[data-pane]").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== k));
    history.replaceState(null, "", `#/report/${id}/${k}`);
  };
  select(tab);
  app.querySelectorAll("[data-tab]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); select(a.dataset.tab); }));
  $("#download").addEventListener("click", () => {
    // The browser's print dialog saves a clean PDF (print styles show every tab and hide the app chrome).
    const old = document.title;
    document.title = `${c.name} - ${d.role.title} - interview report`;
    window.print();
    document.title = old;
  });
  app.querySelectorAll("[data-menu]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openMenu(b); }));
  app.querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", async () => { await send(`/candidates/${id}/decision`, { method: "POST", body: { status: b.dataset.dec } }); reportPage(id, tab); }));
  app.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    select("transcript");
    const el = document.getElementById(`t-${a.dataset.jump}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800);
  }));
}

// ---------- Compare ----------
async function comparePage(roleId, ids, nav = navSeq) {
  if (ids.length < 2) {
    crumbs([["Roles", "#/"], ["Role", `#/role/${roleId}`], ["Compare"]]);
    app.innerHTML = `<div class="empty"><h2>Pick two to four candidates</h2><p>Select scored candidates in the candidates table, then press Compare.</p><div class="row"><a class="btn" href="#/role/${roleId}">Back to candidates</a></div></div>`;
    return;
  }
  const reports = await Promise.all(ids.slice(0, 4).map((x) => get(`/candidates/${x}`)));
  if (stale(nav)) return;
  crumbs([["Roles", "#/"], [reports[0].role.title, `#/role/${roleId}`], ["Compare"]]);
  const names = [...new Set(reports.flatMap((d) => (d.report?.criteria || []).map((x) => x.name)))];
  const cell = (d, name) => {
    const x = d.report?.criteria.find((y) => y.name === name);
    if (!x) return `<td class="muted">Not scored</td>`;
    const [label, cls] = RATING[x.rating], q = x.evidence[0]?.quote;
    return `<td><span class="pill ${cls}">${label}</span> <span class="fig">${x.score || "-"}</span>${q ? `<p class="quote-s"><mark>${esc(q.length > 150 ? q.slice(0, 147) + "..." : q)}</mark></p>` : `<p class="hint">No quote</p>`}</td>`;
  };
  app.innerHTML = `<div class="page-head"><div><h1>Compare candidates</h1><p class="sub">Each cell shows the rating and the candidate's strongest quote.</p></div></div>
    <div class="table-wrap"><table class="table compare"><thead><tr><th>Criterion</th>${reports.map((d) => `<th><a href="#/report/${d.candidate.candidate_id}">${esc(d.candidate.name)}</a></th>`).join("")}</tr></thead><tbody>
      <tr><td><b>Overall</b></td>${reports.map((d) => `<td><span class="fig">${d.report?.overall_score ?? "-"}</span> <span class="muted">/ 10</span>${d.report?.recommendation ? ` <span class="pill ${d.report.recommendation}">${REC[d.report.recommendation]}</span>` : ""}</td>`).join("")}</tr>
      <tr><td>Resume fit</td>${reports.map((d) => `<td class="fig">${d.fit?.score != null ? d.fit.score + "%" : "-"}</td>`).join("")}</tr>
      ${names.map((n) => `<tr><td>${esc(n)}</td>${reports.map((d) => cell(d, n)).join("")}</tr>`).join("")}</tbody></table></div>`;
}

window.addEventListener("hashchange", route);
route();
