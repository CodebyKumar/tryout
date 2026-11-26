// Small DOM and UI helpers shared by every page.

export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (sec) => { sec = Math.max(0, Math.round(sec)); return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`; };
export const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
export const when = (iso, opts = { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) => new Date(iso).toLocaleString(undefined, opts);
export const day = (iso) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

export const skeleton = `<div class="skeleton" aria-hidden="true"><i></i><i></i><i></i></div>`;

export function status(el, msg, err = false) { if (!el) return; el.textContent = msg; el.classList.toggle("err", err); }

// "Working... 12s" while a slow action runs. Returns a stop function.
export function ticking(el, msg) {
  const t0 = Date.now();
  const draw = () => status(el, `${msg} ${Math.round((Date.now() - t0) / 1000)}s`);
  draw();
  const id = setInterval(draw, 1000);
  return () => clearInterval(id);
}

// In-app confirmation dialog (instead of the browser's confirm()). Resolves true when confirmed.
export function confirmDialog({ title, body, confirm = "Confirm", cancel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "dialog";
    dlg.innerHTML = `<form method="dialog"><h2>${esc(title)}</h2>${body ? `<p>${esc(body)}</p>` : ""}
      <div class="dialog-actions"><button value="no" class="btn">${esc(cancel)}</button>
      <button value="yes" class="btn ${danger ? "danger-solid" : "primary"}">${esc(confirm)}</button></div></form>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("close", () => { resolve(dlg.returnValue === "yes"); dlg.remove(); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close("no"); }); // a click outside cancels
    dlg.showModal();
    dlg.querySelector('[value="no"]').focus();
  });
}

// A dialog from HTML. Returns the element; Escape or Cancel removes it.
export function dialog(html, wide = true) {
  const dlg = document.createElement("dialog");
  dlg.className = `dialog${wide ? " wide" : ""}`;
  dlg.innerHTML = html;
  document.body.appendChild(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => dlg.close()));
  dlg.showModal();
  return dlg;
}

export async function copy(text, button) {
  const label = button?.textContent;
  try {
    await navigator.clipboard.writeText(text);
    if (button) { button.textContent = "Copied"; setTimeout(() => (button.textContent = label), 1500); }
  } catch { prompt("Copy this", text); }
}

// ---------- Dropdown: one component for action menus, the account menu and custom selects ----------
// dropdown() returns HTML; its behaviour is wired once for the whole page below (open, close, arrow keys, Escape,
// picking). Picking an item fires a bubbling "pick" event on the .dd element, with detail = the item's value.
const CHEVRON = `<svg class="chev" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const TICK = `<svg class="tick" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// items: [{ label, value?, href?, hint?, danger?, checked? } | { divider: true } | { heading: html }]
export function dropdown({ label, items, cls = "btn", align = "end", ariaLabel = "", chevron = true, select = false, disabled = false }) {
  const item = (it) => {
    if (it.divider) return `<div class="dd-divider" role="separator"></div>`;
    if (it.heading) return `<div class="dd-heading">${it.heading}</div>`;
    const inner = `${select ? TICK : ""}<span class="dd-text"><span>${esc(it.label)}</span>${it.hint ? `<small>${esc(it.hint)}</small>` : ""}</span>`;
    const cl = `dd-item${it.danger ? " danger" : ""}`;
    return it.href
      ? `<a class="${cl}" role="menuitem" href="${esc(it.href)}" tabindex="-1">${inner}</a>`
      : `<button type="button" class="${cl}" role="${select ? "menuitemradio" : "menuitem"}" data-value="${esc(it.value ?? "")}" aria-checked="${!!it.checked}" tabindex="-1">${inner}</button>`;
  };
  return `<div class="dd${select ? " dd-select" : ""}" data-align="${align}">`
    + `<button type="button" class="${cls} dd-btn" aria-haspopup="menu" aria-expanded="false"${ariaLabel ? ` aria-label="${esc(ariaLabel)}"` : ""}${disabled ? " disabled" : ""}><span class="dd-label">${label}</span>${chevron ? CHEVRON : ""}</button>`
    + `<div class="dd-menu" role="menu" hidden>${items.map(item).join("")}</div></div>`;
}

// A select built on the dropdown. A hidden input carries the value, so forms read it like any field; picking fires
// "input" on it, so change tracking works. options: [[value, label, hint?]]
export function selectField({ name, label, options, value, disabled = false, hint = "" }) {
  const current = options.find(([v]) => String(v) === String(value)) || options[0];
  const menu = dropdown({ label: esc(current[1]), cls: "select-btn", align: "start", select: true, ariaLabel: label, disabled,
    items: options.map(([v, l, h]) => ({ value: v, label: l, hint: h, checked: String(v) === String(current[0]) })) });
  return `<div class="field"><span class="field-label">${esc(label)}${hint ? ` <span class="hint">${esc(hint)}</span>` : ""}</span>${menu}<input type="hidden" name="${esc(name)}" value="${esc(current[0])}"></div>`;
}

const menuItems = (menu) => $$(".dd-item", menu);
export function closeMenus(except) {
  $$(".dd-btn[aria-expanded=true]").forEach((b) => { if (b !== except) { b.setAttribute("aria-expanded", "false"); b.nextElementSibling.hidden = true; } });
}
// The open menu is placed against the viewport, so a scrolling table or a dialog never clips it; it opens upward
// when there is no room below. Scrolling or resizing closes it.
function place(btn, menu) {
  const r = btn.getBoundingClientRect(), gap = 4;
  const dd = btn.closest(".dd"), start = dd.dataset.align === "start";
  const width = dd.classList.contains("dd-select") ? `${r.width}px` : ""; // a select's menu matches its field
  Object.assign(menu.style, { position: "fixed", top: "0px", left: "0px", right: "auto", width, minWidth: start ? `${r.width}px` : "" });
  const m = menu.getBoundingClientRect();
  const below = innerHeight - r.bottom - gap >= m.height || r.top < m.height;
  menu.style.top = `${below ? r.bottom + gap : r.top - m.height - gap}px`;
  const left = start ? r.left : r.right - m.width;
  menu.style.left = `${Math.max(8, Math.min(left, innerWidth - m.width - 8))}px`;
}
addEventListener("resize", () => closeMenus());
addEventListener("scroll", (e) => { if (!e.target.closest?.(".dd-menu")) closeMenus(); }, true);

function openMenu(btn, focus = "first") {
  closeMenus(btn);
  btn.setAttribute("aria-expanded", "true");
  const menu = btn.nextElementSibling;
  menu.hidden = false;
  place(btn, menu);
  const list = menuItems(menu);
  (focus === "last" ? list.at(-1) : list.find((x) => x.getAttribute("aria-checked") === "true") || list[0])?.focus();
}
function closeMenu(btn) { btn.setAttribute("aria-expanded", "false"); btn.nextElementSibling.hidden = true; btn.focus(); }

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".dd-btn");
  if (btn) {
    e.stopPropagation(); e.preventDefault();
    return btn.getAttribute("aria-expanded") === "true" ? closeMenu(btn) : openMenu(btn);
  }
  const it = e.target.closest(".dd-item");
  if (!it) return closeMenus();
  const dd = it.closest(".dd"), b = $(".dd-btn", dd);
  e.stopPropagation();
  b.setAttribute("aria-expanded", "false"); b.nextElementSibling.hidden = true;
  if (it.tagName !== "BUTTON") return; // a link item navigates by itself
  if (dd.classList.contains("dd-select")) {
    menuItems(dd).forEach((x) => x.setAttribute("aria-checked", String(x === it)));
    $(".dd-label", b).textContent = $(".dd-text > span", it).textContent;
    const input = dd.parentElement.querySelector("input[type=hidden]");
    if (input) { input.value = it.dataset.value; input.dispatchEvent(new Event("input", { bubbles: true })); }
    b.focus();
  }
  dd.dispatchEvent(new CustomEvent("pick", { bubbles: true, detail: it.dataset.value }));
});
document.addEventListener("keydown", (e) => {
  const btn = e.target.closest?.(".dd-btn");
  if (btn && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); return openMenu(btn, e.key === "ArrowUp" ? "last" : "first"); }
  const menu = e.target.closest?.(".dd-menu");
  if (!menu) return;
  const list = menuItems(menu), i = list.indexOf(document.activeElement), b = menu.previousElementSibling;
  if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
  else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
  else if (e.key === "End") { e.preventDefault(); list.at(-1).focus(); }
  else if (e.key === "Escape") { e.preventDefault(); closeMenu(b); }
  else if (e.key === "Tab") { b.setAttribute("aria-expanded", "false"); menu.hidden = true; }
});

// A small "?" that explains a term on hover, keyboard focus or tap. One floating tooltip for the page, placed against
// the viewport, so a scrolling table cannot clip it (a CSS tooltip inside the table could not show above it).
export const tip = (text) => `<button type="button" class="tip" aria-label="${esc(text)}" data-tip="${esc(text)}">?</button>`;
const bubble = document.createElement("div");
bubble.className = "tooltip";
bubble.setAttribute("role", "tooltip");
bubble.hidden = true;
document.body.appendChild(bubble); // modules run after the page is parsed, so the body exists
function showTip(el) {
  bubble.textContent = el.dataset.tip;
  bubble.hidden = false;
  const r = el.getBoundingClientRect(), b = bubble.getBoundingClientRect();
  const above = r.top - b.height - 8 > 0;
  bubble.style.top = `${above ? r.top - b.height - 8 : r.bottom + 8}px`;
  bubble.style.left = `${Math.max(8, Math.min(r.left + r.width / 2 - b.width / 2, innerWidth - b.width - 8))}px`;
}
const hideTip = () => { bubble.hidden = true; };
document.addEventListener("mouseover", (e) => { const t = e.target.closest?.(".tip"); if (t) showTip(t); });
document.addEventListener("mouseout", (e) => { if (e.target.closest?.(".tip")) hideTip(); });
document.addEventListener("focusin", (e) => { const t = e.target.closest?.(".tip"); if (t) showTip(t); });
document.addEventListener("focusout", (e) => { if (e.target.closest?.(".tip")) hideTip(); });
document.addEventListener("click", (e) => { const t = e.target.closest?.(".tip"); if (t) { e.stopPropagation(); showTip(t); } }, true);
addEventListener("scroll", hideTip, true);

export const LOGO = `<svg class="logo-mark" viewBox="0 0 32 32" aria-hidden="true"><path d="M8 3h16a6 6 0 0 1 6 6v10a6 6 0 0 1-6 6H14l-6.2 4.6c-.7.5-1.6 0-1.6-.8V25A6 6 0 0 1 2 19V9a6 6 0 0 1 6-6z" fill="var(--color-accent)"/><rect x="8" y="9" width="16" height="3.2" rx="1.6" fill="#fff"/><rect x="8" y="15.4" width="11" height="3.2" rx="1.6" fill="var(--color-mark)"/></svg>`;
export const brand = (href = "/") => `<a class="brand" href="${href}" aria-label="TryOut home">${LOGO}<span>TryOut</span></a>`;
