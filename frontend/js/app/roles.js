// Roles list (the workspace home) and Create role: one document in, a full interview plan out.
import { $, day, esc, skeleton, status, ticking } from "../lib/ui.js";
import { app, canWrite, crumbs, get, minutes, sendForm, stale, wireRows } from "./store.js";

const LENGTHS = [5, 10, 15, 20, 30, 45];

export async function rolesPage(nav) {
  const roles = await get("/roles", () => !stale(nav) && rolesPage(nav));
  if (stale(nav)) return;
  crumbs([["Roles"]]);
  const create = canWrite() ? `<a class="btn primary" href="#/new">Create role</a>` : "";
  const head = `<div class="page-head"><h1>Roles</h1><div class="actions">${create}</div></div>`;
  if (!roles.length) {
    app.innerHTML = `${head}<div class="empty"><h2>No roles yet</h2>
      <p>A role holds the interview plan and scoring rubric. Create one from a job description or a template, then add candidates to it.</p>
      ${create ? `<div class="row">${create}</div>` : ""}</div>`;
    return;
  }
  app.innerHTML = `${head}<div class="table-wrap"><table class="table"><thead><tr><th>Role</th><th class="num">Candidates</th><th class="num">Interviewed</th><th class="num">To review</th><th class="num">Length</th><th class="num">Brief</th><th class="end">Created</th></tr></thead><tbody>
    ${roles.map((r) => `<tr class="click" data-href="#/role/${r.role_id}"><td><a class="name" href="#/role/${r.role_id}">${esc(r.title)}</a>${r.company ? `<div class="sub">${esc(r.company)}</div>` : ""}${r.integrity === "strict" ? `<div class="sub">Strict integrity</div>` : ""}</td>
      <td class="num">${r.candidates}</td><td class="num">${r.completed}</td>
      <td class="num">${r.to_review ? `<span class="pill review">${r.to_review}</span>` : "0"}</td>
      <td class="num">${minutes(r.time_budget_sec)} min</td><td class="num">v${r.version}</td><td class="end muted">${day(r.created_at)}</td></tr>`).join("")}</tbody></table></div>`;
  wireRows();
}

export async function newRole(nav) {
  crumbs([["Roles", "#/"], ["Create role"]]);
  if (!canWrite()) {
    app.innerHTML = `<div class="empty"><h2>Creating roles needs an approved account</h2><p>Look around the demo, or wait for the admin to approve your account.</p><div class="row"><a class="btn" href="#/">Back to roles</a></div></div>`;
    return;
  }
  app.innerHTML = `<div class="page-head"><h1>Create role</h1></div>
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
      <aside class="panel" id="tplPanel"><div class="panel-title"><h2>Templates</h2></div><p class="hint">Starter job descriptions. Pick one to fill the form, then edit it.</p><div class="tpl-list" id="tpls">${skeleton}</div></aside>
    </div>`;
  const file = $("#file");
  const showFile = () => ($("#fileName").textContent = file.files[0]?.name || "");
  get("/templates").then((list) => {
    if (stale(nav)) return;
    $("#tpls").innerHTML = list.map((t) => `<button class="tpl" type="button" data-tpl="${t.id}"><b>${esc(t.title)}</b><span>${esc(t.summary)}</span></button>`).join("");
    $("#tpls").addEventListener("click", (e) => {
      const t = list.find((x) => x.id === e.target.closest("[data-tpl]")?.dataset.tpl);
      if (!t) return;
      $("#text").value = t.jd; $("#title").value = t.title.replace(/\s*\(.*\)$/, ""); file.value = ""; showFile();
      app.querySelectorAll(".tpl").forEach((b) => b.classList.toggle("sel", b.dataset.tpl === t.id));
    });
  }).catch(() => $("#tplPanel")?.remove());
  $("#pickFile").addEventListener("click", () => file.click());
  file.addEventListener("change", showFile);
  $("#build").addEventListener("click", async (e) => {
    const fd = new FormData();
    if (file.files[0]) fd.append("file", file.files[0]); else fd.append("text", $("#text").value);
    fd.append("title", $("#title").value.trim());
    fd.append("time_budget_sec", $("#len").value);
    e.target.disabled = true;
    const stop = ticking($("#st"), "Reading the document and designing the interview. Usually under 10 seconds.");
    try { const role = await sendForm("/roles/from-document", fd); stop(); location.hash = `#/role/${role.role_id}/plan`; }
    catch (err) { stop(); status($("#st"), err.message, true); e.target.disabled = false; }
  });
}
