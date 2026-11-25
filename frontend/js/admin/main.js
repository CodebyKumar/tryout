// Admin: what the system is doing now (live interviews against capacity, background jobs, AI use) and the
// accounts, with approve and disable. Only the admin can open it; for anyone else the API answers 404.
import { api, me } from "../lib/api.js";
import { topBar } from "../lib/shell.js";
import { $, $$, confirmDialog, day, esc, plural, tip } from "../lib/ui.js";

const STATUS = { pending: ["Waiting for approval", "review"], active: ["Active", "above"], disabled: ["Disabled", "below"], demo: ["Demo, read-only", ""] };
const n = (x) => Number(x).toLocaleString();

const account = await me();
if (!account) location.href = "/login?next=/admin";
else if (!account.is_admin) location.href = "/app";
else {
  topBar(account);
  $("#refresh").addEventListener("click", load);
  load();
  setInterval(() => !document.hidden && load(), 15000);
}

async function load() {
  try {
    const [o, accounts] = await Promise.all([api("/admin/overview", { signedIn: true }), api("/admin/accounts", { signedIn: true })]);
    drawOverview(o);
    drawAccounts(accounts);
  } catch (e) {
    $("#overview").innerHTML = `<div class="empty"><h2>Couldn't load</h2><p>${esc(e.message)}</p></div>`;
  }
}

function drawOverview(o) {
  const j = o.jobs;
  $("#overview").innerHTML = `<dl class="stats">
      <div><dt>Interviews running ${tip("Interviews with an answer in the last two minutes, out of the most that can run at once on the free AI tier.")}</dt><dd><span class="fig">${o.live_interviews}</span><span class="unit"> of ${o.max_live_interviews}</span></dd></div>
      <div><dt>Jobs queued ${tip("Background work: reading a resume, scoring an interview. Retried up to 3 times.")}</dt><dd><span class="fig">${j.queued}</span></dd></div>
      <div><dt>Jobs running</dt><dd><span class="fig">${j.running}</span></dd></div>
      <div><dt>Jobs failed</dt><dd><span class="fig">${j.failed.length}</span></dd></div>
      <div><dt>Interviewer voice</dt><dd><span class="pill ${o.voice ? "above" : "warn"}">${o.voice ? "On" : "Browser voice"}</span></dd></div>
    </dl>
    ${j.failed.length ? `<div class="banner warn">Failed jobs: ${j.failed.map((f) => `${esc(f.kind)} (${esc(f.error)})`).join("; ")}</div>` : ""}
    <p class="hint">Interviews with no answer for ${j.idle_minutes} minutes are ended and scored automatically. New interviews wait when all ${o.max_live_interviews} slots are in use.</p>`;
  $("#usage").innerHTML = o.usage_24h.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Agent</th><th class="num">Calls</th><th class="num">Tokens in</th><th class="num">Cached</th><th class="num">Tokens out</th><th class="num">Average time</th></tr></thead><tbody>
      ${o.usage_24h.map((u) => `<tr><td>${esc(u.agent.replace(/_/g, " "))}</td><td class="num">${n(u.calls)}</td><td class="num">${n(u.prompt_tokens)}</td><td class="num">${n(u.cached_tokens)}</td><td class="num">${n(u.completion_tokens)}</td><td class="num">${(u.avg_ms / 1000).toFixed(1)} s</td></tr>`).join("")}</tbody></table></div>`
    : `<div class="empty"><h2>No AI calls in the last 24 hours</h2></div>`;
}

function drawAccounts(list) {
  const pending = list.filter((a) => a.status === "pending").length;
  $("#pendingCount").textContent = pending ? `${plural(pending, "account")} waiting for approval` : "";
  $("#accounts").innerHTML = `<div class="table-wrap"><table class="table"><thead><tr><th>Account</th><th>Status</th><th class="num">Roles</th><th class="num">Candidates</th><th class="num">Interviewed</th><th>Joined</th><th class="end"><span class="visually-hidden">Actions</span></th></tr></thead><tbody>
    ${list.map((a) => {
      const [label, cls] = STATUS[a.status];
      const actions = a.id === account.id || a.status === "demo" ? "" : a.status === "active"
        ? `<button type="button" class="btn quiet danger" data-set="disabled" data-id="${a.id}" data-name="${esc(a.name)}">Disable</button>`
        : `<button type="button" class="btn" data-set="active" data-id="${a.id}">${a.status === "pending" ? "Approve" : "Enable"}</button>`;
      return `<tr><td><span class="name">${esc(a.name)}</span>${a.is_admin ? " <span class='pill'>Admin</span>" : ""}<div class="sub">${esc(a.email)}</div></td>
        <td><span class="pill ${cls}">${label}</span></td><td class="num">${a.roles}</td><td class="num">${a.candidates}</td><td class="num">${a.interviews}</td>
        <td class="muted">${day(a.created_at)}</td><td class="end">${actions}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  $$("[data-set]").forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.set === "disabled" && !await confirmDialog({ title: `Disable ${b.dataset.name}?`, confirm: "Disable account", danger: true,
      body: "They are signed out at once and can't sign in again until you enable the account. Their data is kept." })) return;
    b.disabled = true;
    try { await api(`/admin/accounts/${b.dataset.id}/status`, { method: "POST", body: { status: b.dataset.set }, signedIn: true }); load(); }
    catch (e) { b.disabled = false; b.title = e.message; }
  }));
}
