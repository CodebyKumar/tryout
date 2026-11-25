// Talking to the server. Every request has a time limit, so a dropped connection shows an error instead of hanging.
// A 401 on a signed-in page sends the person to sign in and back. Each tab has its own id (X-Client-Id): the server
// lets one tab at a time run an interview.

const TAB_ID = sessionStorage.getItem("tryout-tab") || crypto.randomUUID();
sessionStorage.setItem("tryout-tab", TAB_ID);

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(path, init, timeoutMs) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`/api${path}`, { ...init, signal: ctrl.signal, headers: { ...init.headers, "X-Client-Id": TAB_ID } });
  } catch (e) {
    throw new ApiError(e.name === "AbortError" ? "The server didn't answer in time. Check your connection and try again." : "Couldn't reach the server. Check your connection and try again.", 0);
  } finally { clearTimeout(timer); }
  if (res.status === 401 && init.signedIn) {
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.hash)}`;
    return new Promise(() => {}); // the page is leaving
  }
  if (!res.ok) {
    let msg = `Error ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch {}
    if (Array.isArray(msg)) msg = "Some fields are not valid. Check them and try again."; // FastAPI validation detail
    throw new ApiError(msg, res.status);
  }
  if (!res.headers.get("content-type")?.includes("json")) throw new ApiError("Unexpected response from the server. Reload the page and try again.", res.status);
  return res.json();
}

// JSON request. `signedIn: true` (recruiter and admin pages) redirects to sign in on 401.
export function api(path, opts = {}, timeoutMs = 60000) {
  const { body, ...rest } = opts;
  return request(path, { ...rest, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }, timeoutMs);
}

export function postForm(path, fd, timeoutMs = 90000, signedIn = false) {
  return request(path, { method: "POST", body: fd, headers: {}, signedIn }, timeoutMs);
}

export async function me() {
  try { return await api("/auth/me"); } catch { return null; }
}
