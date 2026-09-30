import { api, escapeHtml, label } from "./api.js";

const rows = document.getElementById("codebook-rows");
const status = document.getElementById("codebook-status");

try {
  const items = await api("/codebook/instructions", { auth: false });
  rows.innerHTML = items.map((i) => {
    const rate = Number(i.success_rate);
    const flag = rate < 0.4 ? ' <span class="badge badge-HIGH">Needs review</span>' : "";
    return `<tr>
      <td class="mono">${escapeHtml(i.id)}</td>
      <td>${escapeHtml(label(i.domain))}</td>
      <td><strong>${escapeHtml(i.title)}</strong><br><span class="muted small">${escapeHtml(i.text)}</span></td>
      <td class="num">${(rate * 100).toFixed(1)}%${flag}</td>
    </tr>`;
  }).join("");
  status.textContent = `${items.length} instructions`;
} catch (err) {
  rows.innerHTML = `<tr><td colspan="4" class="muted">The live codebook is unavailable right now (${escapeHtml(err.message)}).</td></tr>`;
  status.textContent = "Offline";
}
