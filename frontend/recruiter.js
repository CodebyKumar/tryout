// Tryout recruiter app. Routes: #/ · #/new · #/role/ID · #/role/ID/plan · #/report/ID
import { $, api, confirmDialog, esc, fmt, postForm, status, ticking } from "/static/common.js";

const app = $("#app");
const RATING = { above_bar: ["Above the bar", "above", 5 / 6], meets_bar: ["Meets the bar", "meets", 1 / 2], below_bar: ["Below the bar", "below", 1 / 6], not_assessed: ["Not assessed", "", null] };
const REC = { advance: "Advance", hold: "Hold", reject: "Reject" };
const STATUS = { invited: "Invited", in_progress: "Interviewing", completed: "Ready to review", advanced: "Advanced", hold: "On hold", rejected: "Rejected" };
let poll = null;
// Every navigation gets a number. A page that finishes loading after you've moved on (slow network, background
// refresh) sees a newer number and doesn't paint over the page you're on.
let navSeq = 0;
const stale = (nav) => nav !== navSeq;

window.addEventListener("hashchange", route);
route();

async function route() {
  clearInterval(poll);
  const nav = ++navSeq;
  const [, page, id, sub] = location.hash.split("/");
  app.setAttribute("aria-busy", "true");
  try {
    renderNav(page === "role" ? id : null).catch(() => {});
    if (page === "new") return newRole();
    if (page === "role") return await rolePage(id, sub === "plan" ? "plan" : "candidates", nav);
    if (page === "report") return await reportPage(id, nav);
    return await home(nav);
  } catch (e) {
    if (!stale(nav)) app.innerHTML = `<div class="empty"><h3>Couldn't load this page</h3><p>${esc(e.message)}</p><p><button class="btn" onclick="location.reload()">Try again</button></p></div>`;
  } finally { app.removeAttribute("aria-busy"); }
}

async function renderNav(activeId) {
  const roles = await api("/roles");
  $("#roleNav").innerHTML = roles.map((r) => `<a href="#/role/${r.role_id}" class="${r.role_id === activeId ? "on" : ""}">${esc(r.title)}<span>${r.candidates} candidate${r.candidates === 1 ? "" : "s"}</span></a>`).join("");
}

// ---------- Home ----------
async function home(nav = navSeq) {
  const roles = await api("/roles");
  if (stale(nav)) return;
  if (!roles.length) return newRole(true);
  app.innerHTML = `<div class="page-head"><div><h1>Roles</h1><p class="sub">Open a role to invite candidates or review interviews.</p></div></div>
    <div class="panel table-wrap"><table class="table"><thead><tr><th>Role</th><th>Candidates</th><th>Interviewed</th><th>Interview length</th></tr></thead><tbody>
    ${roles.map((r) => `<tr class="click" data-href="#/role/${r.role_id}"><td><div class="name">${esc(r.title)}</div><div class="small faint">${esc(r.company)}</div></td>
      <td class="num">${r.candidates}</td><td class="num">${r.completed}</td><td class="num">${Math.round(r.time_budget_sec / 60)} min</td></tr>`).join("")}</tbody></table></div>`;
  app.querySelectorAll("[data-href]").forEach((tr) => tr.addEventListener("click", () => (location.hash = tr.dataset.href)));
}

// ---------- New role: one document in, full interview plan out ----------
function newRole(first = false) {
  app.innerHTML = `<div class="page-head"><div><h1>${first ? "Set up your first role" : "New role"}</h1>
    <p class="lede">Upload whatever you already have: the job description, interview guidelines, a rubric, or rough notes. Tryout reads it and builds the interview plan and scoring for you. You can adjust it afterwards in plain words.</p></div></div>
    <div class="panel">
      <div class="drop" id="drop" tabindex="0" role="button" aria-label="Upload a hiring document">
        <h2>Drop your hiring document here</h2><p class="muted">PDF, Word or text file. Or click to choose one.</p>
        <p class="file hidden" id="fileName"></p>
        <input type="file" id="file" accept=".pdf,.docx,.txt,.md" class="hidden">
      </div>
      <p class="or">or paste it</p>
      <textarea id="text" rows="7" placeholder="Paste the job description and anything the interviewer should know: must-haves, red flags, topics to avoid, how long the interview should be."></textarea>
      <div class="fields" style="margin-top:16px">
        <label>Role title (optional)<input id="title" placeholder="Read from the document if left empty"></label>
        <label>Interview length<select id="len"><option value="0">As the document says (15 min if not stated)</option><option value="300">5 minutes</option><option value="600">10 minutes</option><option value="900">15 minutes</option><option value="1200">20 minutes</option><option value="1800">30 minutes</option></select></label>
      </div>
      <div class="row end" style="margin-top:18px"><span id="st" class="status"></span><button id="build" class="btn primary">Build interview plan</button></div>
    </div>`;
  const drop = $("#drop"), file = $("#file");
  const pick = () => file.click();
  drop.addEventListener("click", pick);
  drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick()));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) { file.files = e.dataTransfer.files; showFile(); } });
  file.addEventListener("change", showFile);
  function showFile() { $("#fileName").textContent = file.files[0]?.name || ""; $("#fileName").classList.toggle("hidden", !file.files[0]); }

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

// ---------- Role ----------
async function rolePage(id, tab, nav = navSeq) {
  const role = await api(`/roles/${id}`);
  if (stale(nav)) return;
  const reviewed = role.candidates.filter((c) => c.score != null).length;
  app.innerHTML = `<div class="page-head"><div><h1>${esc(role.title)}</h1>
      <p class="sub">${role.company ? `${esc(role.company)}, ` : ""}${Math.round(role.time_budget_sec / 60)} minute interview, ${role.candidates.length} candidate${role.candidates.length === 1 ? "" : "s"}, ${reviewed} interviewed</p></div></div>
    <div class="tabs"><a href="#/role/${id}" class="${tab === "candidates" ? "on" : ""}">Candidates</a><a href="#/role/${id}/plan" class="${tab === "plan" ? "on" : ""}">Interview plan</a></div>
    <div id="body"></div>`;
  tab === "plan" ? planTab(role) : candidatesTab(role);
}

function candidatesTab(role) {
  const link = (c) => `${location.origin}/i/${c.token}`;
  const statusPill = (c) => c.evaluating ? `<span class="pill live">Scoring</span>` : `<span class="pill ${c.status}">${STATUS[c.status]}</span>`;
  $("#body").innerHTML = `
    <div class="panel"><div class="panel-title"><h2>Invite a candidate</h2><span class="small faint">They get a private link and can take the interview any time.</span></div>
      <div class="fields"><label>Full name<input id="cname" autocomplete="off"></label><label>Email<input id="cemail" type="email" autocomplete="off"></label></div>
      <details style="margin-top:12px"><summary class="small muted">Add their resume now (optional, otherwise they upload it before the interview)</summary>
        <textarea id="cresume" rows="5" style="margin-top:8px" placeholder="Paste the resume text"></textarea></details>
      <div class="row end" style="margin-top:14px"><span id="cst" class="status"></span><button id="add" class="btn primary">Create interview link</button></div></div>
    <div class="panel table-wrap">${role.candidates.length ? `<table class="table"><thead><tr><th>Candidate</th><th>Status</th><th>Resume fit</th><th>Score</th><th>Suggested</th><th></th></tr></thead><tbody>
      ${role.candidates.map((c) => {
        const open = c.fit != null || c.score != null || c.status !== "invited";
        return `<tr class="${open ? "click" : ""}" data-id="${c.candidate_id}" data-open="${open}">
          <td><div class="name">${esc(c.name)}</div><div class="small faint">${esc(c.email)}</div></td>
          <td>${statusPill(c)}</td><td class="num">${c.fit != null ? `<a href="#/report/${c.candidate_id}" title="See what the fit is based on">${c.fit}%</a>` : "<span class='faint'>No resume yet</span>"}</td>
          <td class="num">${c.score != null ? `${c.score} / 5` : "-"}</td>
          <td>${c.recommendation ? `<span class="pill ${c.recommendation}">${REC[c.recommendation]}</span>` : "-"}</td>
          <td><div class="row end"><button class="btn quiet" data-copy="${esc(link(c))}">Copy link</button>
            ${c.status !== "invited" || c.fit != null ? `<button class="btn quiet" data-reset="${c.candidate_id}">Reset</button>` : ""}
            <button class="btn quiet danger" data-delete="${c.candidate_id}" data-name="${esc(c.name)}">Delete</button></div></td></tr>`;
      }).join("")}</tbody></table>`
      : `<div class="empty"><h3>No candidates yet</h3><p>Invite someone above. Their interview link works on any laptop with Chrome or Edge.</p></div>`}</div>`;

  $("#add").addEventListener("click", async (e) => {
    if (!$("#cname").value.trim()) return status($("#cst"), "Enter the candidate's name.", true);
    e.target.disabled = true;
    status($("#cst"), $("#cresume").value.trim() ? "Reading the resume..." : "");
    try { await api(`/roles/${role.role_id}/candidates`, { method: "POST", body: { name: $("#cname").value, email: $("#cemail").value, resume: $("#cresume").value } }); rolePage(role.role_id, "candidates"); }
    catch (err) { status($("#cst"), err.message, true); e.target.disabled = false; }
  });
  app.querySelectorAll("tr[data-open='true']").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.closest("button")) location.hash = `#/report/${tr.dataset.id}`; }));
  app.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy link"), 1500); }
    catch { prompt("Interview link", b.dataset.copy); }
  }));
  app.querySelectorAll("[data-reset]").forEach((b) => b.addEventListener("click", async () => {
    if (!await confirmDialog({ title: "Reset this interview?", confirm: "Reset interview",
      body: "The transcript, report, resume and resume fit are cleared. The same link works again, and the candidate uploads their resume again." })) return;
    await api(`/candidates/${b.dataset.reset}/reset`, { method: "POST" });
    rolePage(role.role_id, "candidates");
  }));
  app.querySelectorAll("[data-delete]").forEach((b) => b.addEventListener("click", async () => {
    if (!await confirmDialog({ title: `Delete ${b.dataset.name}?`, confirm: "Delete candidate", danger: true,
      body: "Their resume, transcript and report are permanently removed, and the interview link stops working." })) return;
    await api(`/candidates/${b.dataset.delete}`, { method: "DELETE" });
    rolePage(role.role_id, "candidates");
  }));
  if (role.candidates.some((c) => c.status === "in_progress" || c.evaluating)) {
    const nav = navSeq;
    clearInterval(poll);
    poll = setInterval(() => rolePage(role.role_id, "candidates", nav).catch(() => {}), 5000);
  }
}

function planTab(role) {
  let t = 0;
  const starts = role.sections.map((s) => { const at = t; t += s.time_budget_sec; return at; });
  $("#body").innerHTML = `
    <div class="panel"><div class="panel-title"><h2>Change the plan</h2></div>
      <div class="ask"><label>Describe what you want changed<textarea id="ask" rows="2" placeholder="For example: spend more time on RAG evaluation, drop the logistics question, add a red flag for copy-pasted answers."></textarea></label>
      <button id="apply" class="btn primary">Apply change</button></div><p id="ast" class="status" style="margin-top:8px"></p></div>

    <div class="cols" style="margin-top:16px">
      <div class="panel"><div class="panel-title"><h2>Conversation</h2><span class="small faint">${role.sections.length} parts, ${Math.round(t / 60)} of ${Math.round(role.time_budget_sec / 60)} min planned</span></div>
        <ol class="timeline">${role.sections.map((s, i) => `<li><span class="at">${fmt(starts[i])}</span><div>
          <h3>${esc(s.name)} <span class="faint small">${Math.round(s.time_budget_sec / 6) / 10} min${s.priority === 3 ? ", skipped if short on time" : ""}</span></h3>
          <p class="q">"${esc(s.opening_question)}"</p>
          <p class="small muted">${esc(s.intent)}</p>
          <ul class="evidence-list" style="margin-top:8px">${s.slots.map((x) => `<li>${esc(x.desc)}${x.required ? "" : " <span class='faint'>(if time allows)</span>"}</li>`).join("")}</ul></div></li>`).join("")}</ol></div>

      <div class="panel"><div class="panel-title"><h2>How candidates are scored</h2></div>
        ${role.criteria.map((c) => `<div class="crit-def"><div class="crit-top"><h3>${esc(c.name)}</h3><span class="small faint">weight ${c.weight}</span></div>
          <p class="small muted">${esc(c.description)}</p>
          <div class="bars" style="grid-template-columns:1fr"><div><b>Above the bar</b>${esc(c.above_bar)}</div><div><b>Meets the bar</b>${esc(c.meets_bar)}</div><div><b>Below the bar</b>${esc(c.below_bar)}</div></div></div>`).join("")}
      </div>
    </div>

    <div class="panel" style="margin-top:16px"><details id="manual"><summary><b>Edit everything by hand</b> <span class="small faint">for exact wording</span></summary><div id="editor"></div></details></div>
    ${role.notes || role.jd ? `<div class="panel"><details><summary><b>What Tryout read from your document</b></summary>
      <p class="small muted" style="margin-top:12px;white-space:pre-wrap">${esc(role.jd)}</p>${role.notes ? `<p class="small" style="margin-top:12px;white-space:pre-wrap"><b>Notes for the interviewer</b><br>${esc(role.notes)}</p>` : ""}</details></div>` : ""}`;

  $("#apply").addEventListener("click", async (e) => {
    if (!$("#ask").value.trim()) return status($("#ast"), "Describe the change first.", true);
    e.target.disabled = true;
    const stop = ticking($("#ast"), "Updating the plan...");
    try { await api(`/roles/${role.role_id}/refine`, { method: "POST", body: { instruction: $("#ask").value } }, 90000); stop(); rolePage(role.role_id, "plan"); }
    catch (err) { stop(); status($("#ast"), err.message, true); e.target.disabled = false; }
  });
  $("#manual").addEventListener("toggle", (e) => e.target.open && !$("#editor").innerHTML && manualEditor(role));
}

function manualEditor(role) {
  const slotText = (s) => s.slots.map((x) => `${x.desc}${x.required ? "" : " (optional)"}`).join("\n");
  $("#editor").innerHTML = `${role.sections.map((s, i) => `<div class="edit-block" data-sec="${i}">
      <div class="fields"><label>Part<input data-k="name" value="${esc(s.name)}"></label><label>Minutes<input data-k="min" type="number" min="0.5" step="0.5" value="${s.time_budget_sec / 60}"></label></div>
      <label style="margin-top:10px">Opening question<input data-k="q" value="${esc(s.opening_question)}"></label>
      <label style="margin-top:10px">What to find out, one per line<textarea data-k="slots" rows="${s.slots.length + 1}">${esc(slotText(s))}</textarea></label></div>`).join("")}
    ${role.criteria.map((c, i) => `<div class="edit-block" data-crit="${i}">
      <div class="fields"><label>Criterion<input data-k="name" value="${esc(c.name)}"></label><label>Weight<input data-k="weight" type="number" min="0.5" max="3" step="0.5" value="${c.weight}"></label></div>
      <div class="fields" style="margin-top:10px"><label>Above the bar<textarea data-k="above_bar" rows="2">${esc(c.above_bar)}</textarea></label><label>Meets the bar<textarea data-k="meets_bar" rows="2">${esc(c.meets_bar)}</textarea></label><label>Below the bar<textarea data-k="below_bar" rows="2">${esc(c.below_bar)}</textarea></label></div></div>`).join("")}
    <div class="row end"><span id="est" class="status"></span><button id="saveManual" class="btn primary">Save changes</button></div>`;
  $("#saveManual").addEventListener("click", async () => {
    const v = (el, k) => el.querySelector(`[data-k="${k}"]`).value;
    const sections = role.sections.map((s, i) => {
      const el = app.querySelector(`[data-sec="${i}"]`);
      const slots = v(el, "slots").split("\n").map((l) => l.trim()).filter(Boolean).map((l, j) => ({
        slot_id: s.slots[j]?.slot_id || `s${j + 1}`, desc: l.replace(/\s*\(optional\)$/, ""), required: !/\(optional\)$/.test(l) }));
      return { ...s, name: v(el, "name"), opening_question: v(el, "q"), time_budget_sec: Math.round(+v(el, "min") * 60), slots };
    });
    const criteria = role.criteria.map((c, i) => {
      const el = app.querySelector(`[data-crit="${i}"]`);
      return { ...c, name: v(el, "name"), weight: +v(el, "weight"), above_bar: v(el, "above_bar"), meets_bar: v(el, "meets_bar"), below_bar: v(el, "below_bar") };
    });
    try { await api(`/roles/${role.role_id}`, { method: "PUT", body: { sections, criteria } }); rolePage(role.role_id, "plan"); }
    catch (e) { status($("#est"), e.message, true); }
  });
}

// ---------- Report ----------
const MATCH = { strong: ["Clear evidence", "above"], partial: ["Some evidence", "warn"], none: ["Not in resume", "below"] };

function fitPanel(fit) {
  if (!fit || fit.score == null) return "";
  const group = (must) => fit.items.filter((i) => i.must_have === must);
  const rows = (items) => items.map((i) => `<li class="fit-item"><div class="crit-top"><span>${esc(i.requirement)}</span><span class="pill ${MATCH[i.match][1]}">${MATCH[i.match][0]}</span></div>
      ${i.evidence ? `<p class="small faint">${esc(i.evidence)}</p>` : ""}</li>`).join("");
  return `<div class="panel"><h3>Resume fit</h3><div class="fit">${fit.score}%</div><div class="meter"><div style="width:${fit.score}%"></div></div>
    <p class="small muted">${esc(fit.summary)}</p>
    ${group(true).length ? `<p class="small" style="margin-top:14px"><b>Must-haves</b></p><ul class="fit-list">${rows(group(true))}</ul>` : ""}
    ${group(false).length ? `<p class="small" style="margin-top:14px"><b>Nice to have</b></p><ul class="fit-list">${rows(group(false))}</ul>` : ""}
    <p class="small faint" style="margin-top:14px">How it's calculated: each requirement from the job description is checked against the resume. Clear evidence counts fully, some evidence counts half, and must-haves count twice as much as nice-to-haves.</p></div>`;
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

async function reportPage(id, nav = navSeq) {
  const d = await api(`/candidates/${id}`);
  if (stale(nav)) return;
  const c = d.candidate, r = d.report;
  const back = `<a class="back" href="#/role/${c.role_id}">${esc(d.role.title)}</a>`;
  if (!r) {
    const scoring = d.state === "EVALUATING";
    const note = scoring ? "Scoring the interview. This usually takes under a minute."
      : d.state === "DONE" ? "This interview hasn't been scored." : c.status === "in_progress" ? "Interview in progress." : "Hasn't taken the interview yet.";
    app.innerHTML = `${back}<div class="page-head"><div><h1>${esc(c.name)}</h1><p class="sub">${note}</p></div>
      ${d.state === "DONE" ? `<button id="reeval" class="btn primary">Score interview</button>` : ""}</div>
      <div style="max-width:640px">${fitPanel(d.fit)}</div>`;
    if (scoring) { clearInterval(poll); poll = setInterval(() => reportPage(id, nav).catch(() => {}), 3000); }
    $("#reeval")?.addEventListener("click", async (e) => { e.target.disabled = true; await api(`/candidates/${id}/reevaluate`, { method: "POST" }); reportPage(id); });
    return;
  }
  const quotesByTurn = {};
  r.criteria.forEach((x) => x.evidence.forEach((e) => (quotesByTurn[e.turn_id] ||= []).push(e.quote)));
  const met = r.criteria.filter((x) => x.rating === "above_bar" || x.rating === "meets_bar").length;
  const decision = ["advanced", "hold", "rejected"].includes(c.status) ? c.status : null;
  const first = esc(c.name.split(" ")[0]);

  app.innerHTML = `${back}
    <div class="page-head"><div><h1>${esc(c.name)}</h1><p class="sub">${esc(d.role.title)}, ${c.email ? `${esc(c.email)}, ` : ""}${fmt(d.duration_sec)} interview, ${met} of ${r.criteria.length} criteria met</p></div>
      <button class="btn no-print" id="download">Download report</button></div>
    <div class="cols">
      <div>
        <div class="panel">
          <div class="verdict"><div class="score">${r.overall_score ?? "-"}<small> / 5</small></div>
            <div><span class="pill ${r.recommendation || ""}">${r.recommendation ? `Suggested: ${REC[r.recommendation]}` : "No suggestion"}</span><p class="small muted" style="margin-top:8px;max-width:48ch">${esc(r.recommendation_reason)}</p></div></div>
          <p class="memo">${esc(r.summary)}</p>
          <div class="decide"><span class="small muted">Your decision</span>
            ${[["advanced", "Advance"], ["hold", "Hold"], ["rejected", "Reject"]].map(([s, l]) => `<button class="btn ${decision === s ? "sel" : ""}" data-dec="${s}">${l}</button>`).join("")}</div>
        </div>
        <div class="panel"><div class="panel-title"><h2>Against the criteria</h2><span class="small faint">Highlighted text is the candidate's own words</span></div>
          ${r.criteria.map((x) => {
            const [label, cls, pos] = RATING[x.rating];
            return `<div class="crit"><div class="crit-top"><h3>${esc(x.name)}</h3><span class="pill ${cls}">${label}${x.score ? `, ${x.score} / 5` : ""}</span></div>
              <div class="scale ${pos == null ? "na" : ""}" aria-hidden="true"><span></span><span></span><span></span>${pos != null ? `<i class="dot" style="left:${pos * 100}%"></i>` : ""}</div>
              <div class="scale-labels" aria-hidden="true"><span>Below</span><span>Meets</span><span>Above</span></div>
              ${x.verified ? "" : `<p class="small" style="color:var(--warn);margin-top:8px">No quote backs this rating, so it doesn't count toward the score.</p>`}
              <p class="rationale">${esc(x.rationale)}</p>
              ${x.evidence.map((e) => `<div class="quote"><a href="#" data-jump="${e.turn_id}">${e.at}</a><span><mark>${esc(e.quote)}</mark></span></div>`).join("")}</div>`;
          }).join("")}
        </div>
      </div>
      <div>
        ${fitPanel(d.fit)}
        <div class="panel"><h3>Strengths</h3><ul class="side-list small" style="margin-top:8px">${r.strengths.map((s) => `<li>${esc(s)}</li>`).join("") || "<li class='faint'>None noted</li>"}</ul>
          <h3 style="margin-top:18px">Concerns</h3><ul class="side-list small" style="margin-top:8px">${r.concerns.map((s) => `<li>${esc(s)}</li>`).join("") || "<li class='faint'>None noted</li>"}</ul>
          ${r.resume_flags.length ? `<h3 style="margin-top:18px">Resume claims not backed up</h3><ul class="side-list small" style="margin-top:8px">${r.resume_flags.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
          ${d.flags.length ? `<p class="small faint" style="margin-top:18px">The candidate mentioned personal details (${[...new Set(d.flags.map((f) => f.subtype))].map(esc).join(", ")}). These are never scored.</p>` : ""}</div>
        <div class="panel"><h3>Feedback for ${first}</h3><p class="serif" style="margin-top:8px;font-size:16px">${esc(r.candidate_feedback)}</p>
          <div style="margin-top:14px">${c.feedback_released ? `<span class="small muted">Shared on their interview link.</span>` : `<button id="release" class="btn">Share with candidate</button>`}</div></div>
      </div>
    </div>
    <div class="panel" style="margin-top:16px"><div class="panel-title"><h2>Transcript</h2><span class="small faint">${d.usage.calls} AI calls, ${(d.usage.prompt_tokens + d.usage.completion_tokens).toLocaleString()} tokens</span></div>
      <div class="transcript">${d.transcript.map((t) => `<div class="line ${t.role}" id="t-${t.turn_id}"><span class="t">${t.at}</span><span class="who">${t.role === "user" ? first : "Interviewer"}</span>
        <span class="text">${t.role === "user" ? highlight(t.text, quotesByTurn[t.turn_id] || []) : esc(t.text)}</span></div>`).join("")}</div></div>`;

  $("#download").addEventListener("click", () => {
    // The browser's print dialog saves a clean PDF (print styles hide the app chrome).
    const old = document.title;
    document.title = `${c.name} - ${d.role.title} - interview report`;
    window.print();
    document.title = old;
  });
  app.querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", async () => { await api(`/candidates/${id}/decision`, { method: "POST", body: { status: b.dataset.dec } }); reportPage(id); }));
  $("#release")?.addEventListener("click", async () => { await api(`/candidates/${id}/release_feedback`, { method: "POST" }); reportPage(id); });
  app.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const el = document.getElementById(`t-${a.dataset.jump}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800);
  }));
}
