// One role: header and stats, then a tab each for candidates, the interview plan, scoring and settings.
import { $, $$, confirmDialog, copy, dialog, esc, fmt, openMenu, plural, status, ticking } from "../lib/ui.js";
import { editDialog, fromInput, inviteDialog, windowText } from "./invite.js";
import { DECISION, REC, app, canWrite, crumbs, get, linkFor, minutes, refreshLater, send, stale, wireRows } from "./store.js";

export const ROLE_TABS = [["candidates", "Candidates"], ["plan", "Interview plan"], ["scoring", "Scoring"], ["settings", "Settings"]];
const LENGTHS = [5, 10, 15, 20, 30, 45];
const scored = (c) => c.state === "DONE";
const FILTERS = [
  ["all", "All", () => true],
  ["invited", "Invited", (c) => c.status === "invited"],
  ["live", "In progress", (c) => c.status === "in_progress" || c.state === "EVALUATING"],
  ["review", "To review", (c) => c.status === "completed" && !c.decision],
  ["decided", "Decided", (c) => !!c.decision],
];

export async function rolePage(id, tab, filter, nav) {
  const role = await get(`/roles/${id}`, () => !stale(nav) && rolePage(id, tab, filter, nav));
  if (stale(nav)) return;
  crumbs([["Roles", "#/"], [role.title, `#/role/${id}`], [ROLE_TABS.find(([k]) => k === tab)[1]]]);
  const tabHref = (k) => (k === "candidates" ? `#/role/${id}` : `#/role/${id}/${k}`);
  const count = (test) => role.candidates.filter(test).length;
  const writable = canWrite();
  app.innerHTML = `<div class="page-head"><div><h1>${esc(role.title)}</h1>${role.company ? `<p class="sub">${esc(role.company)}</p>` : ""}</div>
      ${writable ? `<div class="actions"><button type="button" class="btn" id="aiBtn">Edit with AI</button><button type="button" class="btn primary" id="addBtn">Add candidates</button></div>` : ""}</div>
    <dl class="stats">
      <div><dt>Candidates</dt><dd><span class="fig">${role.candidates.length}</span></dd></div>
      <div><dt>Interviewed</dt><dd><span class="fig">${count((c) => c.status === "completed")}</span></dd></div>
      <div><dt>To review</dt><dd><span class="fig">${count((c) => c.status === "completed" && !c.decision)}</span></dd></div>
      <div><dt>Interview length</dt><dd><span class="fig">${minutes(role.time_budget_sec)}</span><span class="unit"> min</span></dd></div>
      <div><dt>Integrity</dt><dd><span class="pill ${role.integrity === "strict" ? "warn" : ""}">${role.integrity === "strict" ? "Strict" : "Standard"}</span></dd></div>
    </dl>
    <nav class="tabs" aria-label="Role">${ROLE_TABS.map(([k, label]) => `<a href="${tabHref(k)}" class="${tab === k ? "on" : ""}" ${tab === k ? 'aria-current="page"' : ""}>${label}${k === "candidates" ? `<span class="count">${role.candidates.length}</span>` : ""}</a>`).join("")}</nav>
    <div id="body"></div>`;
  $("#addBtn")?.addEventListener("click", () => addDialog(role));
  $("#aiBtn")?.addEventListener("click", () => refineDialog(role));
  const reload = () => rolePage(id, tab, filter, nav);
  if (tab === "plan") return planTab(role, reload);
  if (tab === "scoring") return scoringTab(role, reload);
  if (tab === "settings") return settingsTab(role, reload);
  candidatesTab(role, filter, nav);
}

// A brief change makes a new version; candidates already prepared keep the one they got.
function versionWarning(role) {
  const prepared = role.candidates.filter((c) => c.brief_version).length;
  return prepared ? `<div class="banner warn">${plural(prepared, "candidate")} already prepared on brief v${role.version}. Saving creates v${role.version + 1} for new candidates; prepared ones keep theirs.</div>` : "";
}

// ---------- Candidates ----------

function statusCell(c) {
  if (c.prep_status === "failed" && c.status === "invited") return `<span class="pill failed">Resume read failed</span>${canWrite() ? ` <button type="button" class="btn quiet" data-prep="${c.candidate_id}">Retry</button>` : ""}`;
  if (c.state === "EVALUATING") return `<span class="pill live">Scoring</span>`;
  if (c.state === "EVAL_FAILED") return `<span class="pill failed">Scoring failed</span>`;
  if (c.decision) return `<span class="pill ${c.decision}">${DECISION[c.decision]}</span>`;
  if (c.status === "completed") return `<span class="pill review">Ready for review</span>`;
  if (c.status === "in_progress") return `<span class="pill live">Interviewing</span>`;
  if (c.expired) return `<span class="pill failed">Link expired</span>`;
  if (c.prep_status === "pending") return `<span class="pill">Reading resume</span>`;
  if (c.opens_at && new Date(c.opens_at) > new Date()) return `<span class="pill">Scheduled</span>`;
  return `<span class="pill">Invited</span>`;
}

function candidatesTab(role, filter, nav) {
  const body = $("#body");
  const writable = canWrite();
  if (!role.candidates.length) {
    body.innerHTML = `<div class="empty"><h2>No candidates yet</h2><p>Each candidate you add gets a private interview link to send them.</p>
      <div class="row">${writable ? `<button type="button" class="btn" id="emptyAdd">Add candidates</button>` : ""}<a class="btn quiet" href="#/role/${role.role_id}/plan">Check the interview plan first</a></div></div>`;
    $("#emptyAdd")?.addEventListener("click", () => addDialog(role));
    return;
  }
  const [, , test] = FILTERS.find(([k]) => k === filter) || FILTERS[0];
  const list = role.candidates.filter(test);
  const canOpen = (c) => c.fit != null || c.score != null || c.status !== "invited";
  body.innerHTML = `<div class="toolbar"><nav class="filters" aria-label="Filter candidates">${FILTERS.map(([k, label, t]) => `<a href="#/role/${role.role_id}/candidates/${k}" class="${k === filter ? "on" : ""}" ${k === filter ? 'aria-current="true"' : ""}>${label}<span class="count">${role.candidates.filter(t).length}</span></a>`).join("")}</nav></div>
    ${list.length ? `<div class="table-wrap"><table class="table candidates"><thead><tr><th class="check"><span class="visually-hidden">Compare</span></th><th>Candidate</th><th>Status</th><th class="num">Score</th><th>AI suggests</th><th class="num">Resume fit</th><th class="end"><span class="visually-hidden">Actions</span></th></tr></thead><tbody>
      ${list.map((c) => `<tr ${canOpen(c) ? `class="click" data-href="#/report/${c.candidate_id}"` : ""}>
        <td class="check">${scored(c) && c.score != null ? `<input type="checkbox" data-pick="${c.candidate_id}" aria-label="Compare ${esc(c.name)}">` : ""}</td>
        <td data-label="Candidate">${canOpen(c) ? `<a class="name" href="#/report/${c.candidate_id}">${esc(c.name)}</a>` : `<span class="name">${esc(c.name)}</span>`}${c.email ? `<div class="sub">${esc(c.email)}</div>` : ""}${c.status === "invited" ? `<div class="sub">${esc(windowText(c))}</div>` : ""}</td>
        <td data-label="Status">${statusCell(c)}</td>
        <td class="num" data-label="Score">${c.score != null ? `${c.score}<span class="muted"> / 10</span>` : `<span class="muted">-</span>`}</td>
        <td data-label="AI suggests">${c.recommendation ? `<span class="pill ${c.recommendation}">${REC[c.recommendation]}</span>` : `<span class="muted">-</span>`}</td>
        <td class="num" data-label="Resume fit">${c.fit != null ? `${c.fit}%` : `<span class="muted">-</span>`}</td>
        <td class="end">${c.status === "invited" ? `<button type="button" class="btn quiet" data-copy="${esc(linkFor(c))}">Copy link</button>${writable ? `<button type="button" class="btn quiet" data-invite="${c.candidate_id}">Invite</button>` : ""}` : ""}
          ${writable ? `<div class="more"><button type="button" class="btn quiet icon" data-menu aria-haspopup="menu" aria-expanded="false" aria-label="More actions for ${esc(c.name)}">&hellip;</button><div class="menu" role="menu" hidden>
            ${canOpen(c) ? `<a class="btn quiet" role="menuitem" href="#/report/${c.candidate_id}">Open report</a>` : ""}
            <button type="button" class="btn quiet" role="menuitem" data-edit="${c.candidate_id}">${c.status === "invited" ? "Edit or reschedule" : "Edit details"}</button>
            ${c.status !== "invited" || c.expired ? `<button type="button" class="btn quiet" role="menuitem" data-reset="${c.candidate_id}">Reset with a new link</button>` : ""}
            <button type="button" class="btn quiet danger" role="menuitem" data-delete="${c.candidate_id}" data-name="${esc(c.name)}">Delete candidate</button></div></div>` : ""}</td></tr>`).join("")}
      </tbody></table></div>` : `<div class="empty"><h2>Nobody here</h2><p>No candidates match this filter.</p></div>`}
    <div class="pickbar hidden" id="pickbar" role="region" aria-label="Compare"><span id="pickCount"></span><a class="btn primary" id="compare" href="#">Compare</a></div>`;

  const reload = () => rolePage(role.role_id, "candidates", filter, nav);
  const byId = (id) => role.candidates.find((c) => c.candidate_id === id);
  const bar = $("#pickbar"), cmp = $("#compare");
  $$("[data-pick]", body).forEach((box) => box.addEventListener("change", () => {
    const ids = $$("[data-pick]:checked", body).map((x) => x.dataset.pick);
    if (ids.length > 4) { box.checked = false; ids.pop(); }
    bar.classList.toggle("hidden", !ids.length);
    $("#pickCount").textContent = ids.length < 2 ? "Select one more scored candidate to compare" : `${ids.length} selected`;
    cmp.href = `#/role/${role.role_id}/compare/${ids.join(",")}`;
    cmp.setAttribute("aria-disabled", ids.length < 2);
  }));
  wireRows(body);
  $$("[data-copy]", body).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); copy(b.dataset.copy, b); }));
  $$("[data-invite]", body).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); inviteDialog(byId(b.dataset.invite), role); }));
  $$("[data-edit]", body).forEach((b) => b.addEventListener("click", () => editDialog(byId(b.dataset.edit), reload)));
  $$("[data-menu]", body).forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); openMenu(b); }));
  $$("[data-prep]", body).forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    b.disabled = true; b.textContent = "Reading...";
    try { await send(`/candidates/${b.dataset.prep}/prepare`, { method: "POST" }); reload(); }
    catch (err) { b.disabled = false; b.title = err.message; b.textContent = "Still failing, retry"; }
  }));
  $$("[data-reset]", body).forEach((b) => b.addEventListener("click", async () => {
    if (!await confirmDialog({ title: "Reset with a new link?", confirm: "Reset interview",
      body: "The transcript, report, resume and decision are cleared, and the old link stops working. Send the candidate the new link." })) return;
    await send(`/candidates/${b.dataset.reset}/reset`, { method: "POST" });
    reload();
  }));
  $$("[data-delete]", body).forEach((b) => b.addEventListener("click", async () => {
    if (!await confirmDialog({ title: `Delete ${b.dataset.name}?`, confirm: "Delete candidate", danger: true,
      body: "Their resume, transcript and report are permanently removed, and the interview link stops working." })) return;
    await send(`/candidates/${b.dataset.delete}`, { method: "DELETE" });
    reload();
  }));
  if (role.candidates.some((c) => c.status === "in_progress" || c.state === "EVALUATING" || c.prep_status === "pending")) {
    // a refresh redraws the table, so skip it while the recruiter has a row selected or a menu open
    refreshLater(async () => { if (!app.querySelector("[data-pick]:checked, [data-menu][aria-expanded=true], dialog[open]")) await rolePage(role.role_id, "candidates", filter, nav); }, nav);
  }
}

// Add candidates: one row per person, an optional interview window for all of them, then their links.
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/; // the same shape check as the server
function addDialog(role) {
  const dlg = dialog(`<form method="dialog" id="addForm" novalidate><h2>Add candidates</h2>
    <p>Each candidate gets a private interview link. They upload their resume in the lobby before they start.</p>
    <div class="people" role="group" aria-label="Candidates"><div class="people-head" aria-hidden="true"><span>Full name</span><span>Email</span><span></span></div><div id="rows"></div></div>
    <button type="button" class="btn quiet add-row" id="addRow">Add another candidate</button>
    <details class="schedule"><summary>Schedule a window <span class="hint">Optional. Without one, the link works for 14 days.</span></summary>
      <div class="fields"><label>Opens<input id="opens" type="datetime-local"></label><label>Closes<input id="closes" type="datetime-local"></label></div></details>
    <p id="dst" class="status" role="status"></p>
    <div class="dialog-actions"><button class="btn" type="button" data-close>Cancel</button><button class="btn primary" id="create" type="submit">Create link</button></div></form>`);
  const rows = $("#rows", dlg);
  const count = () => rows.children.length;
  const sync = () => {
    $$("[data-remove]", rows).forEach((b) => (b.disabled = count() === 1));
    $("#create", dlg).textContent = count() === 1 ? "Create link" : "Create links";
  };
  let seq = 0;
  const addRow = () => {
    const n = ++seq;
    rows.insertAdjacentHTML("beforeend", `<div class="person">
      <input name="name" autocomplete="off" aria-label="Full name, candidate ${n}" placeholder="Full name">
      <input name="email" type="email" inputmode="email" autocomplete="off" aria-label="Email, candidate ${n}" placeholder="name@example.com">
      <button type="button" class="btn quiet icon" data-remove aria-label="Remove candidate ${n}">&times;</button>
      <p class="field-err" aria-live="polite"></p></div>`);
    const row = rows.lastElementChild;
    $("[data-remove]", row).addEventListener("click", () => { row.remove(); sync(); rows.querySelector("input")?.focus(); });
    $$("input", row).forEach((i) => i.addEventListener("input", () => { i.removeAttribute("aria-invalid"); $(".field-err", row).textContent = ""; }));
    sync();
    $("input", row).focus();
  };
  addRow();
  $("#addRow", dlg).addEventListener("click", addRow);

  // Checks every row before sending anything: a name, a valid email, no email twice. Marks each problem in place.
  const check = () => {
    const seen = new Set(), people = [];
    for (const row of [...rows.children]) {
      const [name, email] = $$("input", row);
      const v = { name: name.value.trim(), email: email.value.trim().toLowerCase(), row };
      if (!v.name && !v.email && rows.children.length > 1) { row.remove(); continue; } // a blank extra row is ignored
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
    const window = { opens_at: fromInput($("#opens", dlg).value), closes_at: fromInput($("#closes", dlg).value) };
    $("#create", dlg).disabled = true;
    const made = [];
    for (const [i, p] of people.entries()) {
      status($("#dst", dlg), `Creating ${i + 1} of ${people.length}...`);
      try { made.push(await send(`/roles/${role.role_id}/candidates`, { method: "POST", body: { name: p.name, email: p.email, ...window } })); p.row.remove(); }
      catch (err) { $(".field-err", p.row).textContent = err.message; $('[name="email"]', p.row).setAttribute("aria-invalid", "true"); }
    }
    if (count()) { // some rows failed: keep them for fixing, and say what was created
      status($("#dst", dlg), `${made.length ? `${plural(made.length, "link")} created. ` : ""}Fix the rows that are left and try again.`, true);
      $("#create", dlg).disabled = false; sync();
      return;
    }
    $("#addForm", dlg).innerHTML = `<h2>${plural(made.length, "link")} ready</h2>
      <p>Send each candidate their link. Invite opens a ready-to-send message in your mailbox.</p>
      <ul class="links">${made.map((c) => `<li><div><span class="name">${esc(c.name)}</span><div class="hint">${esc(windowText(c))}</div></div>
        <div class="row"><button type="button" class="btn" data-copy="${esc(linkFor(c))}">Copy link</button><button type="button" class="btn" data-invite="${c.candidate_id}">Invite</button></div></li>`).join("")}</ul>
      <div class="dialog-actions"><button type="button" class="btn primary" data-close>Done</button></div>`;
    $$("[data-copy]", dlg).forEach((b) => b.addEventListener("click", () => copy(b.dataset.copy, b)));
    $$("[data-invite]", dlg).forEach((b) => b.addEventListener("click", () => inviteDialog(made.find((c) => c.candidate_id === b.dataset.invite), role)));
    $$("[data-close]", dlg).forEach((b) => b.addEventListener("click", () => dlg.close()));
  });
  dlg.addEventListener("close", () => { location.hash = `#/role/${role.role_id}`; window.dispatchEvent(new HashChangeEvent("hashchange")); });
}

// Plain-language change to the whole brief (sections and scoring) through Role Refine.
function refineDialog(role) {
  const dlg = dialog(`<form method="dialog" id="aiForm"><h2>Edit with AI</h2>
    ${versionWarning(role)}
    <label>What should change<textarea id="ask" rows="4" placeholder="For example: spend more time on system design, drop the logistics question, add a red flag for copy-pasted answers."></textarea></label>
    <p id="ast" class="status" role="status"></p>
    <div class="dialog-actions"><button class="btn" type="button" data-close>Cancel</button><button class="btn primary" id="apply" type="submit">Apply change</button></div></form>`);
  $("#ask", dlg).focus();
  $("#aiForm", dlg).addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!$("#ask", dlg).value.trim()) return status($("#ast", dlg), "Describe the change first.", true);
    $("#apply", dlg).disabled = true;
    const stop = ticking($("#ast", dlg), "Updating the brief...");
    try { await send(`/roles/${role.role_id}/refine`, { method: "POST", body: { instruction: $("#ask", dlg).value } }, 90000); stop(); dlg.close(); window.dispatchEvent(new HashChangeEvent("hashchange")); }
    catch (err) { stop(); status($("#ast", dlg), err.message, true); $("#apply", dlg).disabled = false; }
  });
}

async function save(role, changes, el, reload) {
  try { await send(`/roles/${role.role_id}`, { method: "PUT", body: changes }); reload(); }
  catch (e) { status(el, e.message, true); }
}
const v = (el, k) => el.querySelector(`[data-k="${k}"]`).value;

// ---------- Interview plan: the timeline bar, then one ruled row per section ----------
function planTab(role, reload) {
  let t = 0;
  const starts = role.sections.map((s) => { const at = t; t += s.time_budget_sec; return at; });
  $("#body").innerHTML = `<div class="toolbar"><div><h2>Interview plan</h2>
      <p class="hint">${plural(role.sections.length, "part")}, ${minutes(t)} of ${minutes(role.time_budget_sec)} min. The rest is kept for follow-ups and the wrap-up.</p></div>
      ${canWrite() ? `<button type="button" class="btn" id="editPlan">Edit plan</button>` : ""}</div>
    <div class="timebar" aria-hidden="true">${role.sections.map((s) => `<i class="${s.priority === 3 ? "opt" : ""}" style="flex:${s.time_budget_sec}" title="${esc(s.name)}"></i>`).join("")}<i class="opt" style="flex:${Math.max(0, role.time_budget_sec - t)};opacity:.35"></i></div>
    <div id="planBody" class="plan-body"><ol class="plan">${role.sections.map((s, i) => `<li>
      <div class="when"><span class="mono">${fmt(starts[i])}</span><span>${Math.round(s.time_budget_sec / 6) / 10} min</span></div>
      <div><div class="head"><h3>${esc(s.name)}</h3>${s.priority === 3 ? `<span class="pill">Skipped if short on time</span>` : ""}</div>
        <p class="q">“${esc(s.opening_question)}”</p>
        ${s.intent ? `<p class="intent">${esc(s.intent)}</p>` : ""}
        <ul class="slots" aria-label="What the interviewer finds out">${s.slots.map((x) => `<li class="${x.required ? "" : "opt"}">${esc(x.desc)}${x.required ? "" : " (if time allows)"}</li>`).join("")}</ul></div></li>`).join("")}</ol></div>`;
  $("#editPlan")?.addEventListener("click", (e) => { e.target.remove(); planEditor(role, reload); });
}

function planEditor(role, reload) {
  const slotText = (s) => s.slots.map((x) => `${x.desc}${x.required ? "" : " (optional)"}`).join("\n");
  $("#planBody").innerHTML = `${versionWarning(role)}<div class="panel">${role.sections.map((s, i) => `<div class="edit-block" data-sec="${i}">
      <div class="fields"><label>Part name<input data-k="name" value="${esc(s.name)}"></label><label>Minutes<input data-k="min" type="number" inputmode="decimal" min="0.5" step="0.5" value="${s.time_budget_sec / 60}"></label></div>
      <label>Opening question<input data-k="q" value="${esc(s.opening_question)}"></label>
      <label>Purpose<input data-k="intent" value="${esc(s.intent)}"></label>
      <label>What to find out <span class="hint">One per line. End a line with (optional) if it can be skipped.</span><textarea data-k="slots" rows="${s.slots.length + 1}">${esc(slotText(s))}</textarea></label></div>`).join("")}
    <div class="edit-actions"><span id="est" class="status" role="status"></span><button type="button" class="btn" id="cancelEdit">Cancel</button><button type="button" id="saveEdit" class="btn primary">Save plan</button></div></div>`;
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

// ---------- Scoring: how scores are made, then one disclosure row per criterion ----------
function scoringTab(role, reload) {
  const total = role.criteria.reduce((a, c) => a + c.weight, 0) || 1;
  $("#body").innerHTML = `<div class="toolbar"><div><h2>Scoring</h2>
      <p class="hint">${plural(role.criteria.length, "criterion", "criteria")}, each scored 1 to 10</p></div>
      ${canWrite() ? `<button type="button" class="btn" id="editCrit">Edit scoring</button>` : ""}</div>
    <dl class="rules">
      <div><dt>Criterion score</dt><dd>Below the bar 1 to 4, meets 5 to 7, above 8 to 10. A rating counts only when its quote is found in the transcript.</dd></div>
      <div><dt>Overall score</dt><dd>Weighted average out of 10 of the quote-backed criteria, shown once they cover half the weight.</dd></div>
      <div><dt>AI suggestion</dt><dd>Worked out in code from the verified ratings, not taken from the model. Reject under 5 or a weak key criterion; advance from 6 with every key criterion backed.</dd></div>
    </dl>
    <div id="critBody">${role.criteria.length ? `<div class="crits">${role.criteria.map((c) => `<details class="crit"><summary>
        <div><h3>${esc(c.name)}</h3>${c.description ? `<p>${esc(c.description)}</p>` : ""}</div>
        <div class="weight"><span><span class="fig">${Math.round((c.weight / total) * 100)}%</span> of score (weight ${c.weight})</span><div class="meter"><div style="width:${(c.weight / total) * 100}%"></div></div></div></summary>
      <div class="bars"><div class="above"><b>Above the bar, 8 to 10</b>${esc(c.above_bar) || "-"}</div><div class="meets"><b>Meets the bar, 5 to 7</b>${esc(c.meets_bar) || "-"}</div><div class="below"><b>Below the bar, 1 to 4</b>${esc(c.below_bar) || "-"}</div></div></details>`).join("")}</div>` : `<div class="empty"><h2>No criteria</h2><p>Use Edit with AI to add scoring criteria.</p></div>`}</div>`;
  $("#editCrit")?.addEventListener("click", (e) => { e.target.remove(); scoringEditor(role, reload); });
}

function scoringEditor(role, reload) {
  $("#critBody").innerHTML = `${versionWarning(role)}<div class="panel">${role.criteria.map((c, i) => `<div class="edit-block" data-crit="${i}">
      <div class="fields"><label>Criterion<input data-k="name" value="${esc(c.name)}"></label><label>Weight <span class="hint">0.5 to 3</span><input data-k="weight" type="number" inputmode="decimal" min="0.5" max="3" step="0.5" value="${c.weight}"></label></div>
      <label>What it measures<input data-k="description" value="${esc(c.description)}"></label>
      <div class="fields"><label>Above the bar<textarea data-k="above_bar" rows="3">${esc(c.above_bar)}</textarea></label><label>Meets the bar<textarea data-k="meets_bar" rows="3">${esc(c.meets_bar)}</textarea></label><label>Below the bar<textarea data-k="below_bar" rows="3">${esc(c.below_bar)}</textarea></label></div></div>`).join("")}
    <div class="edit-actions"><span id="est" class="status" role="status"></span><button type="button" class="btn" id="cancelEdit">Cancel</button><button type="button" id="saveEdit" class="btn primary">Save scoring</button></div></div>`;
  $("#cancelEdit").addEventListener("click", reload);
  $("#saveEdit").addEventListener("click", () => {
    const criteria = role.criteria.map((c, i) => {
      const el = app.querySelector(`[data-crit="${i}"]`);
      return { ...c, name: v(el, "name"), weight: +v(el, "weight"), description: v(el, "description"), above_bar: v(el, "above_bar"), meets_bar: v(el, "meets_bar"), below_bar: v(el, "below_bar") };
    });
    save(role, { criteria }, $("#est"), reload);
  });
}

// ---------- Settings: role details, integrity mode, the job description, delete ----------
// Saves only what changed. Title, company and integrity are labels; length and notes change the brief (a new version).
function settingsTab(role, reload) {
  const len = minutes(role.time_budget_sec);
  const opts = [...new Set([...LENGTHS, len])].sort((a, b) => a - b);
  const prepared = role.candidates.filter((c) => c.brief_version).length;
  const off = canWrite() ? "" : "disabled";
  $("#body").innerHTML = `<div class="cols">
    <form class="panel form" id="settings"><div class="panel-title"><h2>Role details</h2></div>
      <div class="fields"><label>Role title<input name="title" required autocomplete="off" value="${esc(role.title)}" ${off}></label><label>Company<input name="company" autocomplete="organization" value="${esc(role.company)}" ${off}></label></div>
      <label>Interview length<select name="len" ${off}>${opts.map((m) => `<option value="${m}" ${m === len ? "selected" : ""}>${m} minutes</option>`).join("")}</select></label>
      <label>Notes for the interviewer<textarea name="notes" rows="5" placeholder="Must-haves, red flags, topics to avoid." ${off}>${esc(role.notes)}</textarea></label>
      <fieldset class="choice"><legend>Integrity checks during the interview</legend>
        <label class="option"><input type="radio" name="integrity" value="standard" ${role.integrity === "standard" ? "checked" : ""} ${off}><span><b>Standard</b>Tab switches, leaving full screen, copy and paste, a second screen and browser extensions are noted on the report.</span></label>
        <label class="option"><input type="radio" name="integrity" value="strict" ${role.integrity === "strict" ? "checked" : ""} ${off}><span><b>Strict</b>Also requires full screen to start and pauses the interview when the candidate leaves it, blocks copy, paste and right-click, and refuses to start while a detectable extension is on. Needs a computer.</span></label>
      </fieldset>
      <p class="banner warn hidden" id="newVersion">Saving creates brief v${role.version + 1}.${prepared ? ` ${plural(prepared, "candidate")} already prepared keep v${role.version}.` : ""}</p>
      ${off ? "" : `<div class="row end"><span id="sst" class="status" role="status"></span><button type="submit" class="btn primary" id="saveSettings" disabled>Save changes</button></div>`}</form>
    <div>
      <section class="panel"><div class="panel-title"><h2>Job description</h2></div><div class="source">${esc(role.jd) || "None saved."}</div></section>
      ${off ? "" : `<section class="panel danger-zone"><div class="panel-title"><h2>Delete role</h2></div><p class="hint">Removes the role with every candidate, transcript and report in it.</p><div class="row"><button type="button" class="btn danger" id="deleteRole">Delete role</button></div></section>`}
    </div></div>`;
  if (off) return;
  const form = $("#settings");
  const changes = () => {
    const f = new FormData(form);
    const next = { title: f.get("title").trim(), company: f.get("company").trim(), notes: f.get("notes"), time_budget_sec: +f.get("len") * 60, integrity: f.get("integrity") };
    return Object.fromEntries(Object.entries(next).filter(([k, val]) => val !== role[k]));
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
  $("#deleteRole").addEventListener("click", async () => {
    if (!await confirmDialog({ title: `Delete ${role.title}?`, confirm: "Delete role", danger: true,
      body: `${plural(role.candidates.length, "candidate")} and their transcripts and reports are permanently removed, and their links stop working.` })) return;
    await send(`/roles/${role.role_id}`, { method: "DELETE" });
    location.hash = "#/";
  });
}
