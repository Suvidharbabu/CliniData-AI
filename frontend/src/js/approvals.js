import "../css/demo.css";
import { api, escapeHtml, label, toast } from "./api.js";
import { renderSessionBar } from "./session-bar.js";
import { requireSession } from "./supabase.js";

const $ = (id) => document.getElementById(id);
let tab = "open";
let items = [];

function timeLeft(deadline) {
  const ms = new Date(deadline) - Date.now();
  if (ms <= 0) return "overdue";
  const h = Math.floor(ms / 3.6e6);
  return h >= 24 ? `${Math.floor(h / 24)} d ${h % 24} h left` : `${h} h left`;
}

function renderApprovals() {
  const open = (a) => a.status === "pending" || a.status === "escalated";
  const list = items.filter((a) => (tab === "open" ? open(a) : !open(a)));
  $("approvals").innerHTML = list.length ? list.map((a) => `
    <article class="card approval" data-id="${a.id}">
      <div class="approval-head">
        <span class="badge badge-${a.severity}">${a.severity}</span>
        <strong>${escapeHtml(`${a.framework} ${a.article_ref}`)}</strong><span class="muted">${escapeHtml(a.title)}</span>
        <span class="badge">${label(a.gap_type)}</span>
        ${a.status === "escalated" ? '<span class="badge badge-HIGH">Escalated</span>' : ""}
        <span class="muted small" style="margin-left:auto">${open(a) ? timeLeft(a.deadline) : `${a.status} by ${label(a.approver_role)} · ${new Date(a.decided_at).toLocaleString()}`}</span>
      </div>
      <div>${escapeHtml(a.summary)}<div class="muted small">${escapeHtml(a.detail || "")}</div></div>
      <div class="small muted">AI confidence ${Math.round(Number(a.confidence) * 100)}% · residual risk ${Number(a.risk_score).toFixed(1)}/25 ·
        requires <strong>${label(a.required_role)}</strong> · from query "${escapeHtml(a.query_text)}"</div>
      ${open(a) ? `
      <div class="approval-actions">
        <label class="visually-hidden" for="c-${a.id}">Decision comments</label>
        <textarea id="c-${a.id}" placeholder="Decision comments (recorded in the audit log)" maxlength="2000"></textarea>
        <button class="btn btn-primary btn-sm" data-decision="approved" type="button">Approve &amp; create remediation</button>
        <button class="btn btn-danger btn-sm" data-decision="rejected" type="button">Reject</button>
      </div>` : a.comments ? `<div class="small">Comments: ${escapeHtml(a.comments)}</div>` : ""}
    </article>`).join("")
    : `<div class="card empty-state">${tab === "open" ? 'No open approvals. Run a gap analysis in the <a href="/demo.html">demo</a> to create some.' : "No decisions yet."}</div>`;
}

async function loadApprovals() {
  try {
    items = await api("/approvals");
    renderApprovals();
  } catch (err) {
    $("approvals").innerHTML = `<div class="alert alert-error">${escapeHtml(err.message)}</div>`;
  }
}

async function loadTasks() {
  try {
    const tasks = await api("/remediations");
    $("tasks").innerHTML = tasks.length ? tasks.map((t) => `
      <tr>
        <td><span class="badge badge-${t.priority}">${t.priority}</span></td>
        <td><strong>${escapeHtml(t.title)}</strong><div class="small muted">${escapeHtml(t.policy_template)}</div></td>
        <td style="white-space:nowrap">${escapeHtml(t.deadline)}</td>
        <td><label class="visually-hidden" for="s-${t.id}">Status</label>
          <select id="s-${t.id}" data-task="${t.id}" style="width:auto">
            ${["open", "in_progress", "complete"].map((s) => `<option value="${s}"${s === t.status ? " selected" : ""}>${label(s)}</option>`).join("")}
          </select></td>
      </tr>`).join("") : '<tr><td colspan="4" class="muted">No remediation tasks yet. Approve a gap to create one.</td></tr>';
  } catch (err) {
    $("tasks").innerHTML = `<tr><td colspan="4" class="muted">${escapeHtml(err.message)}</td></tr>`;
  }
}

document.querySelector(".tabs").addEventListener("click", (event) => {
  const btn = event.target.closest("[data-tab]");
  if (!btn) return;
  tab = btn.dataset.tab;
  document.querySelectorAll("[data-tab]").forEach((b) => {
    const on = b === btn;
    b.setAttribute("aria-selected", String(on));
    b.className = `btn btn-sm ${on ? "btn-secondary" : "btn-ghost"}`;
  });
  renderApprovals();
});

$("approvals").addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-decision]");
  if (!btn) return;
  const card = btn.closest("[data-id]");
  const id = card.dataset.id;
  card.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  try {
    const res = await api(`/approvals/${id}`, {
      method: "PATCH", body: { decision: btn.dataset.decision, comments: $(`c-${id}`).value },
    });
    toast(res.remediation_task ? `Approved. Remediation task due ${res.remediation_task.deadline}.` : "Rejected.", "ok");
    await Promise.all([loadApprovals(), loadTasks()]);
  } catch (err) {
    toast(err.message, "error", 7000);
    card.querySelectorAll("button").forEach((b) => { b.disabled = false; });
  }
});

$("tasks").addEventListener("change", async (event) => {
  const sel = event.target.closest("select[data-task]");
  if (!sel) return;
  try {
    await api(`/remediations/${sel.dataset.task}`, { method: "PATCH", body: { status: sel.value } });
    toast("Task updated.", "ok");
  } catch (err) {
    toast(err.message, "error");
  }
});

if (await requireSession()) {
  renderSessionBar($("session-bar")).catch((err) => { $("session-bar").textContent = err.message; });
  loadApprovals();
  loadTasks();
}
