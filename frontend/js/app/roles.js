// Roles list (the workspace home) and Create role: one document in, a full interview plan out.
import { $, day, esc, selectField, skeleton, status, ticking, tip } from "../lib/ui.js";
import { app, canWrite, crumbs, get, minutes, sendForm, stale, wireRows } from "./store.js";

const LENGTHS = [5, 10, 15, 20, 30, 45];

// The whole flow as a checklist, ticked from real data, so a new recruiter sees where they are and what's next.
function gettingStarted(roles) {
  const first = roles[0];
  const sum = (k) => roles.reduce((a, r) => a + r[k], 0);
  const steps = [
    [roles.length > 0, "Create a role", "Paste a job description or pick a template. The AI drafts the interview plan and the scoring rubric; you can edit both.", `<a class="btn primary" href="#/new">Create role</a>`],
    [sum("candidates") > 0, "Add a candidate", "Each candidate gets a private interview link. To see what candidates see, add yourself.", first ? `<a class="btn primary" href="#/role/${first.role_id}">Open ${esc(first.title)}</a>` : ""],
    [sum("completed") > 0, "The candidate takes the interview", "Send the link with Invite, or open it yourself. The report is ready about a minute after the interview ends.", first ? `<a class="btn" href="#/role/${first.role_id}">See candidates</a>` : ""],
    [sum("completed") > sum("to_review"), "Read the report and decide", "Every score shows the quotes it rests on. Advance, hold or reject; the AI only suggests.", ""],
  ];
  if (steps.every(([done]) => done)) return "";
  const next = steps.findIndex(([done]) => !done);
  return `<section class="panel start" aria-labelledby="startTitle"><div class="panel-title"><h2 id="startTitle">Get started</h2><span class="hint">${steps.filter(([d]) => d).length} of 4 done</span></div>
    <ol class="start-steps">${steps.map(([done, title, text, action], i) => `<li class="${done ? "done" : i === next ? "next" : ""}">
      <span class="start-mark" aria-hidden="true">${done ? "✓" : i + 1}</span>
      <div><h3>${title}${done ? `<span class="visually-hidden"> (done)</span>` : ""}</h3>${i === next ? `<p>${text}</p>${action ? `<div class="row">${action}</div>` : ""}` : ""}</div></li>`).join("")}</ol></section>`;
}

export async function rolesPage(nav) {
  const roles = await get("/roles", () => !stale(nav) && rolesPage(nav));
  if (stale(nav)) return;
  crumbs([["Roles"]]);
  const create = canWrite() ? `<a class="btn primary" href="#/new">Create role</a>` : "";
  const head = `<div class="page-head"><div><h1>Roles</h1><p class="sub">A role holds one interview plan and scoring rubric, and the candidates interviewed with it.</p></div><div class="actions">${roles.length ? create : ""}</div></div>`;
  const start = canWrite() ? gettingStarted(roles) : "";
  if (!roles.length) {
    app.innerHTML = `${head}${start || `<div class="empty"><h2>No roles yet</h2><p>Roles you create appear here.</p></div>`}`;
    return;
  }
  app.innerHTML = `${head}${start}<div class="table-wrap"><table class="table"><thead><tr><th>Role</th><th class="num">Candidates</th><th class="num">Interviewed</th><th class="num">To review ${tip("Interviewed and scored, with no decision yet.")}</th><th class="num">Length</th><th class="end">Created</th></tr></thead><tbody>
    ${roles.map((r) => `<tr class="click" data-href="#/role/${r.role_id}"><td><a class="name" href="#/role/${r.role_id}">${esc(r.title)}</a>${r.company ? `<div class="sub">${esc(r.company)}</div>` : ""}${r.integrity === "strict" ? `<div class="sub">Strict integrity</div>` : ""}</td>
      <td class="num">${r.candidates}</td><td class="num">${r.completed}</td>
      <td class="num">${r.to_review ? `<span class="pill review">${r.to_review}</span>` : "0"}</td>
      <td class="num">${minutes(r.time_budget_sec)} min</td><td class="end muted">${day(r.created_at)}</td></tr>`).join("")}</tbody></table></div>`;
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
          ${selectField({ name: "len", label: "Interview length", value: 0, options: [[0, "As the document says", "15 minutes if it doesn't say"], ...LENGTHS.map((m) => [m * 60, `${m} minutes`])] })}
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
    fd.append("time_budget_sec", $("[name=len]").value);
    e.target.disabled = true;
    const stop = ticking($("#st"), "Reading the document and designing the interview. Usually under 10 seconds.");
    try { const role = await sendForm("/roles/from-document", fd); stop(); location.hash = `#/role/${role.role_id}/plan`; }
    catch (err) { stop(); status($("#st"), err.message, true); e.target.disabled = false; }
  });
}
