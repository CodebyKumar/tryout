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

// Row action menus: one open at a time; an outside click, Escape or picking an item closes it.
export function closeMenus() { $$("[data-menu][aria-expanded=true]").forEach((b) => { b.setAttribute("aria-expanded", "false"); b.nextElementSibling.hidden = true; }); }
export function openMenu(btn) {
  const wasOpen = btn.getAttribute("aria-expanded") === "true";
  closeMenus();
  if (wasOpen) return;
  btn.setAttribute("aria-expanded", "true");
  btn.nextElementSibling.hidden = false;
  btn.nextElementSibling.querySelector("[role^=menuitem]")?.focus();
}
document.addEventListener("click", (e) => { if (!e.target.closest(".menu") || e.target.closest("[role^=menuitem]")) closeMenus(); });
document.addEventListener("keydown", (e) => {
  const open = document.querySelector("[data-menu][aria-expanded=true]");
  if (e.key === "Escape" && open) { closeMenus(); open.focus(); }
});

export const LOGO = `<svg class="logo-mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="var(--color-accent)"/><path d="M8 9.5h16v3.6h-6.2V21l-3.6 3.2V13.1H8z" fill="#fff"/><rect x="8" y="18.2" width="5" height="3" rx="1" fill="var(--color-mark)"/></svg>`;
export const brand = (href = "/") => `<a class="brand" href="${href}" aria-label="TryOut home">${LOGO}<span>TryOut</span></a>`;
