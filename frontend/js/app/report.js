// A candidate's report: header and decision, stat strip, summary, then one tab per kind of evidence. Also the
// side-by-side comparison of two to four candidates.
import { $, $$, dropdown, esc, fmt, plural, status, tip, when } from "../lib/ui.js";
import { DECISION, RATING, REC, app, canWrite, crumbs, get, refreshLater, send, stale } from "./store.js";

const MATCH = { strong: ["Clear evidence", "above"], partial: ["Some evidence", "warn"], none: ["Not in resume", "below"] };
const LEVEL = { none: ["No activity noted", ""], some: ["Some activity", "warn"], review: ["Worth a look", "below"] };
const STARS = ["", "Poor", "Fair", "Good", "Very good", "Excellent"];

// Every browser check the room runs, whether it fired, and when. Never scored, never seen by the evaluator.
const CHECKS = [
  [["tab_hidden", "window_blur"], "Left the interview tab or window"], [["fullscreen_exit"], "Left full screen"],
  [["paste"], "Pasted text"], [["copy"], "Copied text"], [["blocked"], "Tried a blocked action (strict mode)"],
  [["multi_screen"], "Second screen connected"], [["extension"], "Browser extension detected"],
];

function fitPane(fit) {
  if (!fit || fit.score == null) return `<div class="empty"><h2>No resume read</h2><p>The candidate hasn't shared a resume, or it couldn't be read.</p></div>`;
  return `<div class="pane-head"><p>${esc(fit.summary)}</p></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>Requirement</th><th>Type</th><th>Match</th><th>From the resume</th></tr></thead><tbody>
    ${[...fit.items].sort((a, b) => b.must_have - a.must_have).map((i) => `<tr><td>${esc(i.requirement)}</td><td class="muted nowrap">${i.must_have ? "Must-have" : "Nice to have"}</td>
      <td><span class="pill ${MATCH[i.match][1]}">${MATCH[i.match][0]}</span></td><td class="sub">${esc(i.evidence) || "-"}</td></tr>`).join("")}</tbody></table></div>`;
}

function integrityPane(g) {
  const rows = CHECKS.map(([kinds, label]) => {
    const hits = g.events.filter((e) => kinds.includes(e.kind));
    const evidence = hits.map((e) => `<li><span class="mono">${fmt(e.at_sec)}</span>${e.seconds ? ` for ${Math.round(e.seconds)}s` : ""}${e.detail ? `, ${esc(e.detail)}` : ""}</li>`).join("");
    return `<tr><td>${label}</td><td>${hits.length ? `<span class="pill warn">${plural(hits.length, "time")}</span>` : `<span class="pill above">Not seen</span>`}</td>
      <td>${hits.length ? `<ul class="evidence">${evidence}</ul>` : `<span class="empty-val">Never</span>`}</td></tr>`;
  }).join("");
  return `<p class="hint pane-note">These are signals from the candidate's browser, for context. They are never part of the score. A web page cannot see a second device or every extension, so "Not seen" is not proof.</p>
    <div class="table-wrap"><table class="table"><thead><tr><th>Check</th><th>Result</th><th>When</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// How the interview was run: per exchange, what the Turn Agent proposed and what code decided. This is where "the
// AI proposes, code decides" can be seen.
function tracePane(trace) {
  if (!trace.length) return `<div class="empty"><h2>No exchanges yet</h2></div>`;
  const ms = (x) => (x ? `${(x / 1000).toFixed(1)} s` : "-");
  return `<p class="hint pane-note">For each answer: what the Turn Agent proposed, what the code kept or changed, and what it cost.</p>
    <ol class="trace">${trace.map((t) => `<li class="trace-row">
      <div class="trace-time"><span class="mono">${esc(t.at)}</span></div>
      <div class="trace-body">
        ${t.answer ? `<p class="trace-answer"><span class="who">Candidate</span>${esc(t.answer)}</p>` : ""}
        <p class="trace-said"><span class="who">Interviewer</span>${esc(t.said)}</p>
        ${t.decision ? `<p class="trace-decision"><b>Code decided:</b> ${esc(t.decision)}${t.section_before && t.section_after !== t.section_before ? `, moved from ${esc(t.section_before)} to ${esc(t.section_after || "wrap-up")}` : ""}</p>` : ""}
        ${(t.overrides || []).map((o) => `<p class="trace-override"><b>Overrode:</b> ${esc(o)}</p>`).join("")}
        ${t.proposal ? `<details class="trace-proposal"><summary>Turn Agent proposal</summary><pre>${esc(JSON.stringify(t.proposal, null, 2))}</pre></details>` : ""}
        ${t.model ? `<p class="trace-cost">${esc(t.model)}, AI ${ms(t.agent_ms)}${t.stt_ms ? `, speech to text ${ms(t.stt_ms)}` : ""}, ${t.prompt_tokens} tokens in (${t.cached_tokens} cached), ${t.completion_tokens} out</p>` : ""}
      </div></li>`).join("")}</ol>`;
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

// The downloadable report: a paper document built from the same data, not a print of the screen.
function printReport(d) {
  const c = d.candidate, r = d.report, g = d.integrity;
  const total = d.role.criteria.reduce((a, x) => a + x.weight, 0) || 1;
  const weight = (id) => Math.round(((d.role.criteria.find((x) => x.criterion_id === id)?.weight || 0) / total) * 100);
  const flagged = g ? CHECKS.map(([kinds, label]) => [label, g.events.filter((e) => kinds.includes(e.kind))]).filter(([, hits]) => hits.length) : [];
  const date = new Date(r.created_at).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
  const items = (title, list) => (list.length ? `<div><h3>${title}</h3><ul>${list.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "");
  return `<article class="print-report">
    <header><p class="brand">TryOut</p><h1>${esc(c.name)}</h1><p>${esc(d.role.title)}${c.email ? `, ${esc(c.email)}` : ""}</p><p class="muted">Interview report, ${date}, ${fmt(d.duration_sec)} long</p></header>
    <table class="facts"><tr>
      <td><span>Overall score</span><b>${r.overall_score != null ? `${r.overall_score} / 10` : "Not enough evidence"}</b></td>
      <td><span>AI suggests</span><b>${r.recommendation ? REC[r.recommendation] : "No suggestion"}</b></td>
      <td><span>Decision</span><b>${c.decision ? DECISION[c.decision] : "Not decided"}</b></td>
      <td><span>Resume fit</span><b>${d.fit?.score != null ? `${d.fit.score}%` : "No resume read"}</b></td>
    </tr></table>
    <section><h2>Summary</h2><p>${esc(r.summary)}</p>${r.recommendation_reason ? `<p><b>Why the suggestion:</b> ${esc(r.recommendation_reason)}</p>` : ""}</section>
    <section class="two">${items("Strengths", r.strengths)}${items("Concerns", r.concerns)}${items("Resume claims not backed up", r.resume_flags)}</section>
    <section><h2>Scores by criterion</h2><table class="crit-table"><thead><tr><th>Criterion</th><th>Weight</th><th>Rating</th><th>Score</th><th>Evidence from the interview</th></tr></thead><tbody>
      ${r.criteria.map((x) => `<tr><td>${esc(x.name)}</td><td>${weight(x.criterion_id)}%</td><td>${RATING[x.rating][0]}</td><td>${x.score != null && x.verified ? `${x.score} / 10` : "Not counted"}</td>
        <td>${x.evidence.map((e) => `<p>${e.at} “${esc(e.quote)}”</p>`).join("") || `<p class="muted">${x.verified ? "No evidence" : "Not backed by a quote, not counted"}</p>`}</td></tr>`).join("")}</tbody></table></section>
    <section><h2>Integrity</h2>${flagged.length ? `<ul>${flagged.map(([label, hits]) => `<li>${label}: ${hits.map((e) => `${fmt(e.at_sec)}${e.seconds ? ` (${Math.round(e.seconds)}s)` : ""}${e.kind === "extension" ? ` ${esc(e.detail)}` : ""}`).join(", ")}</li>`).join("")}</ul>` : "<p>No issues noted.</p>"}</section>
    ${d.experience ? `<section><h2>Candidate rating of the interview</h2><p>${d.experience.stars} / 5, ${STARS[d.experience.stars]}${d.experience.comment ? `: “${esc(d.experience.comment)}”` : ""}</p></section>` : ""}
  </article>`;
}

export async function reportPage(id, tab, nav) {
  const d = await get(`/candidates/${id}`, () => !stale(nav) && reportPage(id, tab, nav));
  if (stale(nav)) return;
  const c = d.candidate, r = d.report;
  crumbs([["Roles", "#/"], [d.role.title, `#/role/${c.role_id}`], [c.name]]);
  if (!r) {
    const scoring = d.state === "EVALUATING";
    const note = scoring ? "Scoring the interview. This usually takes under a minute."
      : d.state === "EVAL_FAILED" ? `Scoring failed; the transcript is safe. ${esc(d.eval_error)}`
      : d.state === "DONE" ? "This interview hasn't been scored." : c.status === "in_progress" ? "Interview in progress." : "Hasn't taken the interview yet.";
    const retry = canWrite() && (d.state === "DONE" || d.state === "EVAL_FAILED");
    app.innerHTML = `<div class="page-head"><div><h1>${esc(c.name)}</h1><p class="sub">${note}</p></div>
      ${retry ? `<div class="row"><span id="rst" class="status" role="status"></span><button type="button" id="reeval" class="btn primary">${d.state === "DONE" ? "Score interview" : "Retry scoring"}</button></div>` : ""}</div>
      ${d.fit?.score != null ? `<section class="panel"><div class="panel-title"><h2>Resume fit</h2><span class="fit">${d.fit.score}%</span></div>${fitPane(d.fit)}</section>` : ""}`;
    if (scoring || c.status === "in_progress") refreshLater(() => reportPage(id, tab, nav), nav, 3000);
    $("#reeval")?.addEventListener("click", async (e) => {
      e.target.disabled = true; status($("#rst"), "Scoring...");
      try { await send(`/candidates/${id}/reevaluate`, { method: "POST" }, 90000); reportPage(id, tab, nav); }
      catch (err) { status($("#rst"), err.message, true); e.target.disabled = false; }
    });
    return;
  }
  const quotesByTurn = {};
  r.criteria.forEach((x) => x.evidence.forEach((e) => (quotesByTurn[e.turn_id] ||= []).push(e.quote)));
  const met = r.criteria.filter((x) => x.rating === "above_bar" || x.rating === "meets_bar").length;
  const decision = c.decision;
  const first = esc(c.name.split(" ")[0]);
  const g = d.integrity;
  const tabs = [
    ["summary", "Summary", null],
    ["evidence", "Evidence", r.criteria.length],
    ["transcript", "Transcript", d.transcript.length],
    ["resume", "Resume fit", null],
    ...(g ? [["integrity", "Integrity", g.events.length || null]] : []),
    ["trace", "How it decided", null],
    ["rating", "Candidate rating", null],
  ];
  if (!tabs.some(([k]) => k === tab)) tab = "summary";
  const list = (title, items) => `<div><h3>${title}</h3><ul class="side-list">${items.map((s) => `<li>${esc(s)}</li>`).join("") || "<li class='muted'>None noted</li>"}</ul></div>`;
  const decide = canWrite()
    ? `<div id="decide">${dropdown({ label: decision ? DECISION[decision] : "Make a decision", cls: `btn ${decision ? "" : "primary"}`, select: true, items: [
        { value: "advanced", label: "Advance", hint: "Move to the next round", checked: decision === "advanced" },
        { value: "hold", label: "Hold", hint: "Keep for later", checked: decision === "hold" },
        { value: "rejected", label: "Reject", hint: "Not moving forward", checked: decision === "rejected", danger: true },
        ...(decision ? [{ divider: true }, { value: "", label: "Clear decision" }] : []),
      ] })}</div>`
    : decision ? `<span class="pill ${decision}">${DECISION[decision]}</span>` : "";

  app.innerHTML = `<div class="page-head"><h1>${esc(c.name)}</h1>
      <div class="actions"><button type="button" class="btn quiet no-print" id="download">Download</button>${decide}</div></div>
    ${d.decisions.length ? `<p class="hint decision-log">Decision history: ${d.decisions.map((x) => `${x.to ? DECISION[x.to] : "cleared"} on ${when(x.at)}`).join(", ")}</p>` : ""}

    <div class="role-layout">
      <aside class="role-side">
        <nav class="side-tabs" role="tablist" aria-label="Report">${tabs.map(([k, label, n]) => `<a href="#/report/${id}/${k}" role="tab" data-tab="${k}" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}"><span>${label}</span>${n != null ? `<span class="count">${n}</span>` : ""}</a>`).join("")}</nav>
        <section class="overview" aria-label="Overview">
          <dl class="facts">
            <div><dt>Score</dt><dd>${r.overall_score != null ? `${r.overall_score} / 10` : `<span class="muted">Not enough evidence</span>`}</dd></div>
            <div><dt>AI suggests ${tip("Worked out in code from the verified ratings, not taken from the model. The decision is yours.")}</dt><dd>${r.recommendation ? `<span class="pill ${r.recommendation}">${REC[r.recommendation]}</span>` : `<span class="pill">None</span>`}</dd></div>
            <div><dt>Criteria met</dt><dd>${met} of ${r.criteria.length}</dd></div>
            <div><dt>Resume fit ${tip("How much of the role's requirements the resume shows, read by the AI before the interview.")}</dt><dd>${d.fit?.score != null ? `${d.fit.score}%` : `<span class="empty-val">No resume read</span>`}</dd></div>
            <div><dt>Integrity ${tip("Browser signals during the interview, such as leaving the tab. Context only, never scored.")}</dt><dd>${g ? `<span class="pill ${LEVEL[g.level][1]}">${LEVEL[g.level][0]}</span>` : `<span class="empty-val">No data</span>`}</dd></div>
            <div><dt>Length</dt><dd>${fmt(d.duration_sec)}</dd></div>
          </dl>
        </section>
      </aside>
      <div class="role-main">
    <section class="pane summary" data-pane="summary">
      <p class="memo">${esc(r.summary)}</p>
      ${r.recommendation_reason ? `<p class="reason"><b>Why the suggestion:</b> ${esc(r.recommendation_reason)}</p>` : ""}
      <div class="lists">${list("Strengths", r.strengths)}${list("Concerns", r.concerns)}${r.resume_flags.length ? list("Resume claims not backed up", r.resume_flags) : ""}</div>
      ${d.flags.some((f) => f.type !== "injection") ? `<p class="hint">The candidate mentioned personal details (${[...new Set(d.flags.filter((f) => f.type !== "injection").map((f) => f.subtype))].map(esc).join(", ")}). These are never scored.</p>` : ""}
      ${d.flags.some((f) => f.type === "injection") ? `<p class="hint">The candidate tried to give the AI instructions. The interviewer kept to the interview; see How it decided.</p>` : ""}
    </section>

    <section class="pane" data-pane="evidence">
      <div class="ledger">${r.criteria.map((x) => {
        const [label, cls] = RATING[x.rating];
        return `<article class="ledger-row"><div class="lg-score">${x.score ? `<span class="fig">${x.score}</span><span class="small muted">/ 10</span>` : `<span class="empty-val">Not scored</span>`}</div>
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
    <section class="pane" data-pane="trace" id="tracePane"><div class="skeleton" aria-hidden="true"><i></i><i></i></div></section>
    <section class="pane" data-pane="rating">${ratingPane(d.experience)}</section>
      </div>
    </div>
    ${printReport(d)}`;

  let traced = false;
  const select = (k) => {
    $$("[data-tab]").forEach((a) => { a.classList.toggle("on", a.dataset.tab === k); a.setAttribute("aria-selected", a.dataset.tab === k); });
    $$("[data-pane]").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== k));
    history.replaceState(null, "", `#/report/${id}/${k}`);
    if (k === "trace" && !traced) {
      traced = true; // loaded only when opened: it is the largest part of the report
      get(`/candidates/${id}/trace`).then((t) => !stale(nav) && ($("#tracePane").innerHTML = tracePane(t)))
        .catch((e) => ($("#tracePane").innerHTML = `<div class="empty"><h2>Couldn't load the trace</h2><p>${esc(e.message)}</p></div>`));
    }
  };
  select(tab);
  $$("[data-tab]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); select(a.dataset.tab); }));
  $("#download").addEventListener("click", () => {
    // The print dialog saves a clean PDF (print styles show the paper report and hide the app).
    const old = document.title;
    document.title = `${c.name} - ${d.role.title} - interview report`;
    window.print();
    document.title = old;
  });
  $("#decide")?.addEventListener("pick", async (e) => {
    await send(`/candidates/${id}/decision`, { method: "POST", body: { decision: e.detail || null } });
    reportPage(id, tab, nav);
  });
  $$("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    select("transcript");
    const el = document.getElementById(`t-${a.dataset.jump}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800);
  }));
}

export async function comparePage(roleId, ids, nav) {
  if (ids.length < 2) {
    crumbs([["Roles", "#/"], ["Role", `#/role/${roleId}`], ["Compare"]]);
    app.innerHTML = `<div class="empty"><h2>Pick two to four candidates</h2><p>Tick scored candidates in the candidates table, then press Compare.</p><div class="row"><a class="btn" href="#/role/${roleId}">Back to candidates</a></div></div>`;
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
      <tr><td>Resume fit</td>${reports.map((d) => `<td class="fig">${d.fit?.score != null ? d.fit.score + "%" : `<span class="empty-val">No resume read</span>`}</td>`).join("")}</tr>
      ${names.map((n) => `<tr><td>${esc(n)}</td>${reports.map((d) => cell(d, n)).join("")}</tr>`).join("")}</tbody></table></div>`;
}
