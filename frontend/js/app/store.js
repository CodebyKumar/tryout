// State shared by the recruiter screens: the signed-in account, navigation, a read cache, and the page frame.
import { api, postForm } from "../lib/api.js";
import { $, esc } from "../lib/ui.js";

export const state = { account: null };
export const app = $("#app");

// Every navigation gets a number. A page that finishes loading after you've moved on (slow network, background
// refresh) sees a newer number and doesn't paint over the page you're on.
let navSeq = 0;
export const nextNav = () => ++navSeq;
export const current = () => navSeq;
export const stale = (nav) => nav !== navSeq;

// Reads come from the cache first, so moving between pages and tabs is instant; each read also asks the server
// again in the background and redraws only if the answer changed. Every write clears the cache.
const cache = new Map();
export async function get(path, redraw) {
  if (!cache.has(path)) { cache.set(path, await api(path, { signedIn: true })); return cache.get(path); }
  api(path, { signedIn: true }).then((fresh) => {
    const changed = JSON.stringify(fresh) !== JSON.stringify(cache.get(path));
    cache.set(path, fresh);
    if (changed) redraw?.();
  }).catch(() => {});
  return cache.get(path);
}
export const send = (path, opts, ms) => api(path, { ...opts, signedIn: true }, ms).finally(() => cache.clear());
export const sendForm = (path, fd) => postForm(path, fd, 90000, true).finally(() => cache.clear());

// One background refresh at a time (a live interview, a report being scored); navigation stops it.
let poll = null;
export function refreshLater(fn, nav, ms = 5000) { clearInterval(poll); poll = setInterval(() => !stale(nav) && fn().catch(() => {}), ms); }
export const stopRefresh = () => clearInterval(poll);

const BACK = `<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// One back link above the page title, to the parent page, the same on every page. The top page (Roles) has none.
// items: the path from Roles to this page, as [label, href].
export function crumbs(items) {
  const parent = items.at(-2), el = $("#crumbs");
  el.hidden = !parent;
  el.innerHTML = parent ? `<a class="back-link" href="${parent[1]}">${BACK}<span>${esc(parent[0])}</span></a>` : "";
  document.title = `${items.at(-1)[0]} - TryOut`;
}

// Whole table rows open their link; clicks on buttons, links and menus inside the row keep their own meaning.
export function wireRows(root = app) {
  root.querySelectorAll("[data-href]").forEach((tr) => tr.addEventListener("click", (e) => {
    if (!e.target.closest("button, a, input, .dd, .tip")) location.hash = tr.dataset.href;
  }));
}

export const canWrite = () => state.account?.status === "active";
export const minutes = (sec) => Math.round(sec / 60);
export const linkFor = (c) => `${location.origin}/i/${c.token}`;

export const RATING = { above_bar: ["Above the bar", "above"], meets_bar: ["Meets the bar", "meets"], below_bar: ["Below the bar", "below"], not_assessed: ["Not assessed", ""] };
export const REC = { advance: "Advance", hold: "Hold", reject: "Reject" };
export const DECISION = { advanced: "Advanced", hold: "On hold", rejected: "Rejected" };
