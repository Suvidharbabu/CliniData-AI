import { api, escapeHtml, label, toast } from "./api.js";

const ROLE_HELP = {
  compliance_officer: "asks questions; cannot approve",
  compliance_manager: "can approve HIGH gaps",
  cco: "can approve CRITICAL and HIGH gaps",
  auditor: "read-only reviewer",
};

/** Renders the signed-in user's role switcher and quota. Returns the profile. */
export async function renderSessionBar(el, { onChange } = {}) {
  const me = await api("/me");
  const paint = () => {
    el.innerHTML = `
      <span><strong>${escapeHtml(me.email)}</strong></span>
      <label class="muted" for="role-select">Demo role</label>
      <select id="role-select" aria-describedby="role-help">
        ${me.roles.map((r) => `<option value="${r}"${r === me.role ? " selected" : ""}>${label(r)}</option>`).join("")}
      </select>
      <span class="muted small" id="role-help">${escapeHtml(ROLE_HELP[me.role] || "")}</span>
      <span class="badge" id="quota-badge">${me.queries_used} / ${me.query_limit} queries today</span>`;
    el.querySelector("#role-select").addEventListener("change", async (event) => {
      try {
        const { role } = await api("/me", { method: "PATCH", body: { role: event.target.value } });
        me.role = role;
        paint();
        toast(`You are now acting as ${label(role)}.`, "ok");
        onChange?.(me);
      } catch (err) {
        toast(err.message, "error");
        event.target.value = me.role;
      }
    });
  };
  paint();
  me.bumpQuota = () => {
    me.queries_used += 1;
    const badge = el.querySelector("#quota-badge");
    if (badge) badge.textContent = `${me.queries_used} / ${me.query_limit} queries today`;
  };
  return me;
}
