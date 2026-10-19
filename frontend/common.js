export const $ = (s, root = document) => root.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (sec) => { sec = Math.max(0, Math.round(sec)); return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`; };

// Every request has a time limit so a dropped connection (flaky wifi, a tunnel) shows an error instead of hanging.
// The extra header stops VS Code dev tunnels from answering API calls with their warning page.
async function request(path, init, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`/api${path}`, { ...init, signal: ctrl.signal, headers: { ...init.headers, "X-Tunnel-Skip-AntiPhishing-Page": "true" } });
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "The server didn't answer in time. Check your connection and try again." : "Couldn't reach the server. Check your connection and try again.");
  } finally { clearTimeout(timer); }
  if (!res.ok) {
    let msg = `Error ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  if (!res.headers.get("content-type")?.includes("json")) throw new Error("Unexpected response from the server. If you're using a shared link, reopen it and try again.");
  return res.json();
}

export function api(path, opts = {}, timeoutMs = 60000) {
  return request(path, { ...opts, headers: { "Content-Type": "application/json" }, body: opts.body && JSON.stringify(opts.body) }, timeoutMs);
}

export function postForm(path, fd, timeoutMs = 90000) {
  return request(path, { method: "POST", body: fd, headers: {} }, timeoutMs);
}

export function status(el, msg, err = false) { if (!el) return; el.textContent = msg; el.classList.toggle("err", err); }

// "Working... 12s" while a slow action runs. Returns a stop function.
export function ticking(el, msg) {
  const t0 = Date.now();
  const draw = () => status(el, `${msg} ${Math.round((Date.now() - t0) / 1000)}s`);
  draw();
  const id = setInterval(draw, 1000);
  return () => clearInterval(id);
}

// In-app confirmation dialog (replaces the browser's confirm()). Resolves true when confirmed.
export function confirmDialog({ title, body, confirm = "Confirm", cancel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "dialog";
    dlg.innerHTML = `<form method="dialog"><h2>${esc(title)}</h2>${body ? `<p>${esc(body)}</p>` : ""}
      <div class="dialog-actions"><button value="no" class="btn">${esc(cancel)}</button>
      <button value="yes" class="btn ${danger ? "danger-solid" : "primary"}">${esc(confirm)}</button></div></form>`;
    document.body.appendChild(dlg);
    dlg.addEventListener("close", () => { resolve(dlg.returnValue === "yes"); dlg.remove(); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close("no"); }); // click outside cancels
    dlg.showModal();
    dlg.querySelector('[value="no"]').focus();
  });
}
