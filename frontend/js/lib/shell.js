// The top bar shared by the workspace and the admin page: logo, main links, and the account menu (sign out).
import { api } from "./api.js";
import { $, brand, dropdown, esc } from "./ui.js";

const initials = (name) => name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();

export function topBar(account) {
  $("#brand").innerHTML = brand("/app#/");
  $("#adminLink").hidden = !account.is_admin;
  $("#account").innerHTML = dropdown({
    label: `<span class="avatar" aria-hidden="true">${esc(initials(account.name))}</span><span class="who-name">${esc(account.name.split(" ")[0])}</span>`,
    cls: "btn quiet account-btn", ariaLabel: `Account: ${account.name}`,
    items: [
      { heading: `<b>${esc(account.name)}</b><span>${esc(account.email)}</span>${account.status === "active" ? "" : `<span class="pill">${account.status === "demo" ? "Demo, read-only" : "Waiting for approval"}</span>`}` },
      ...(account.is_admin ? [{ label: "Admin", href: "/admin" }] : []),
      { label: "Home page", href: "/" },
      { divider: true },
      { label: "Sign out", value: "signout" },
    ],
  });
  $("#account").addEventListener("pick", async (e) => {
    if (e.detail !== "signout") return;
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    location.href = "/";
  });
}
