// Invites and scheduling. TryOut sends no email itself: the recruiter sends the invite from their own mailbox.
// One click opens a filled-in Gmail draft; "Other mail app" opens the system's mail app; "Copy message" covers the
// rest. A calendar file (.ics) is offered when the interview has a start time.
import { $, copy, dialog, esc, status, when } from "../lib/ui.js";
import { linkFor, minutes, send, state } from "./store.js";

// datetime-local inputs work in local time without a zone; the API takes ISO timestamps in UTC.
export const toInput = (iso) => (iso ? new Date(new Date(iso).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
export const fromInput = (v) => (v ? new Date(v).toISOString() : null);

export function windowText(c) {
  const opens = c.opens_at && new Date(c.opens_at) > new Date() ? c.opens_at : null;
  if (opens) return `Opens ${when(opens)}, closes ${when(c.closes_at)}`;
  return c.closes_at ? `Link works until ${when(c.closes_at)}` : "";
}

function message(c, role, reminder) {
  const first = c.name.split(" ")[0];
  const at = role.company ? ` at ${role.company}` : "";
  const length = `${minutes(role.time_budget_sec)}-minute`;
  const opens = c.opens_at && new Date(c.opens_at) > new Date();
  const timing = opens
    ? `You can start it any time between ${when(c.opens_at)} and ${when(c.closes_at)}.`
    : `The link works until ${when(c.closes_at)}.`;
  const subject = reminder ? `Reminder: your interview for ${role.title}${at}` : `Interview for ${role.title}${at}`;
  const body = [
    `Hi ${first},`,
    "",
    reminder
      ? `A reminder about your ${length} screening interview for the ${role.title} role${at}.`
      : `You're invited to a ${length} screening interview for the ${role.title} role${at}. It is a voice conversation with an AI interviewer that asks about your experience and follows up on your answers. The hiring team then reviews the conversation.`,
    "",
    `Your private link: ${linkFor(c)}`,
    timing,
    "",
    `You'll need a quiet place, a microphone and an up-to-date browser. You can type your answers instead of speaking if you prefer.${
      role.integrity === "strict" ? " This interview runs on a computer, in full screen, with browser extensions turned off." : ""}`,
    "",
    "Best,",
    state.account?.name || "",
  ].join("\n");
  return { subject, body };
}

// iCalendar text for the scheduled start, one event as long as the interview.
function ics(c, role) {
  const stamp = (d) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const start = new Date(c.opens_at);
  const end = new Date(start.getTime() + role.time_budget_sec * 1000);
  const text = (s) => s.replace(/([,;\\])/g, "\\$1").replace(/\n/g, "\\n");
  return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TryOut//Interview//EN", "BEGIN:VEVENT",
    `UID:${c.candidate_id}@tryout`, `DTSTAMP:${stamp(new Date())}`, `DTSTART:${stamp(start)}`, `DTEND:${stamp(end)}`,
    `SUMMARY:${text(`Interview: ${role.title}`)}`, `DESCRIPTION:${text(`Your private interview link: ${linkFor(c)}`)}`, `URL:${linkFor(c)}`,
    "END:VEVENT", "END:VCALENDAR"].join("\r\n");
}

export function inviteDialog(c, role) {
  const draw = (reminder) => {
    const m = message(c, role, reminder);
    const to = encodeURIComponent(c.email || "");
    const gmail = `https://mail.google.com/mail/?view=cm&fs=1&to=${to}&su=${encodeURIComponent(m.subject)}&body=${encodeURIComponent(m.body)}`;
    const mailto = `mailto:${to}?subject=${encodeURIComponent(m.subject)}&body=${encodeURIComponent(m.body)}`;
    return `<form method="dialog"><h2>${reminder ? "Send a reminder" : "Invite"} ${esc(c.name)}</h2>
      <p>The message opens in your own mailbox, ready to send.${c.email ? "" : " Add an email to this candidate to fill in the recipient."}</p>
      <div class="segmented" role="radiogroup" aria-label="Message"><button type="button" class="btn ${reminder ? "" : "sel"}" data-kind="invite" aria-pressed="${!reminder}">Invite</button><button type="button" class="btn ${reminder ? "sel" : ""}" data-kind="reminder" aria-pressed="${reminder}">Reminder</button></div>
      <div class="message"><p class="message-subject">${esc(m.subject)}</p><pre class="message-body">${esc(m.body)}</pre></div>
      <p id="ist" class="status" role="status"></p>
      <div class="dialog-actions wrap">
        <button type="button" class="btn" data-close>Close</button>
        ${c.opens_at && new Date(c.opens_at) > new Date() ? `<button type="button" class="btn" id="ics">Calendar file</button>` : ""}
        <button type="button" class="btn" id="copyMsg">Copy message</button>
        <a class="btn" href="${esc(mailto)}">Other mail app</a>
        <a class="btn primary" href="${esc(gmail)}" target="_blank" rel="noopener">Open in Gmail</a>
      </div></form>`;
  };
  const dlg = dialog(draw(false));
  const wire = () => {
    dlg.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dlg.close()));
    dlg.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => { dlg.innerHTML = draw(b.dataset.kind === "reminder"); wire(); }));
    $("#copyMsg", dlg).addEventListener("click", (e) => {
      const subject = $(".message-subject", dlg).textContent, body = $(".message-body", dlg).textContent;
      copy(`Subject: ${subject}\n\n${body}`, e.target);
    });
    $("#ics", dlg)?.addEventListener("click", () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([ics(c, role)], { type: "text/calendar" }));
      a.download = `interview-${c.name.replace(/\W+/g, "-").toLowerCase()}.ics`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
  };
  wire();
}

// Edit a candidate: name, email, and the interview window (reschedule, or extend an expired link).
export function editDialog(c, done) {
  const started = c.status !== "invited";
  const dlg = dialog(`<form method="dialog" id="editForm" novalidate><h2>Edit ${esc(c.name)}</h2>
    <div class="fields"><label>Full name<input name="name" value="${esc(c.name)}" autocomplete="off"></label>
      <label>Email<input name="email" type="email" value="${esc(c.email)}" autocomplete="off"></label></div>
    ${started ? `<p class="hint">The interview has started, so its window can no longer change.</p>` : `<div class="fields">
      <label>Opens <span class="hint">Empty: any time</span><input name="opens" type="datetime-local" value="${toInput(c.opens_at)}"></label>
      <label>Closes<input name="closes" type="datetime-local" value="${toInput(c.closes_at)}"></label></div>`}
    <p id="est" class="status" role="status"></p>
    <div class="dialog-actions"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary" type="submit">Save changes</button></div></form>`, false);
  $("#editForm", dlg).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { name: f.get("name"), email: f.get("email"), opens_at: fromInput(f.get("opens")), closes_at: fromInput(f.get("closes")) };
    try { await send(`/candidates/${c.candidate_id}`, { method: "PUT", body }); dlg.close(); done(); }
    catch (err) { status($("#est", dlg), err.message, true); }
  });
}
