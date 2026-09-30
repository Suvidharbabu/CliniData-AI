import "../css/demo.css";
import { api, escapeHtml, label, toast } from "./api.js";
import { renderGraph } from "./graph-view.js";
import { renderMarkdown } from "./markdown.js";
import { renderSessionBar } from "./session-bar.js";
import { requireSession } from "./supabase.js";

const $ = (id) => document.getElementById(id);
const form = $("query-form");
const runBtn = $("run-btn");

// Planned steps, shown while the request is in flight (approximate timings in ms).
const PLAN = [
  ["Orchestrator", "Planning scope and routing codebook instructions", 1500],
  ["Retriever", "HyDE query expansion", 1500],
  ["Retriever", "Dense + sparse retrieval, RRF, rerank", 2000],
  ["Graph Traversal", "Multi-hop expansion in Neo4j", 1200],
  ["Gap Mapper", "Checking control coverage and evidence", 300],
  ["Constraint Verifier", "Comparing SLAs with statutory deadlines", 300],
  ["Cross-Reference Agent", "Detecting compound obligations", 300],
  ["Risk Scorer", "Scoring residual risk", 300],
  ["Regulatory Reporter", "Claude is writing the cited analysis", 15000],
  ["Hallucination Guard", "Validating citations", 300],
  ["Approval Gate", "Routing CRITICAL/HIGH gaps to approvers", 300],
];

let me = null;
let current = null;
let graphApi = null;
let planTimer = null;

// ---------------------------------------------------------------- session
const session = await requireSession();
if (session) {
  try {
    me = await renderSessionBar($("session-bar"));
  } catch (err) {
    $("session-bar").innerHTML = `<span class="alert alert-error">${escapeHtml(err.message)}</span>`;
  }
  loadHistory();
}

async function loadHistory() {
  try {
    const runs = await api("/agent/runs");
    const list = $("history");
    if (!runs.length) { list.innerHTML = '<li class="muted small">No runs yet.</li>'; return; }
    list.innerHTML = runs.map((r) => `<li><button type="button" data-run="${r.id}" ${r.status !== "completed" ? "disabled" : ""}>
        ${escapeHtml(r.query_text)}
        <span class="when">${new Date(r.started_at).toLocaleString()} · ${r.status}${r.guard_passed === false ? " · guard flagged" : ""}</span>
      </button></li>`).join("");
  } catch { /* history is optional */ }
}

$("history").addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-run]");
  if (!btn) return;
  try {
    const result = await api(`/agent/runs/${btn.dataset.run}`);
    if (result.answer === undefined) throw new Error("This run did not complete.");
    $("query").value = result.query;
    render(result);
  } catch (err) {
    toast(err.message, "error");
  }
});

$("examples").addEventListener("click", (event) => {
  const btn = event.target.closest(".example");
  if (!btn) return;
  $("query").value = btn.textContent.trim();
  form.requestSubmit();
});

// ---------------------------------------------------------------- run
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("query").value.trim();
  if (query.length < 5) { toast("Please enter a longer question.", "error"); return; }
  runBtn.disabled = true;
  runBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span> Running…';
  $("error-box").hidden = true;
  $("empty-state").hidden = true;
  for (const id of ["answer-card", "gaps-card", "graph-card", "context-grid"]) $(id).hidden = true;
  startPlan();
  try {
    const result = await api("/agent/query", { method: "POST", body: { query } });
    me?.bumpQuota();
    render(result);
    loadHistory();
  } catch (err) {
    stopPlan(true);
    $("error-box").textContent = err.message;
    $("error-box").hidden = false;
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Run analysis";
  }
});

function startPlan() {
  $("timeline-card").hidden = false;
  $("run-meta").textContent = "Running…";
  $("timeline").innerHTML = PLAN.map(([agent, action]) =>
    `<li><span class="dot"></span><div><span class="agent">${agent}</span> <span class="action">${action}</span></div><span class="ms"></span></li>`).join("");
  const items = [...$("timeline").children];
  let i = 0;
  const advance = () => {
    items.forEach((li, j) => { li.classList.toggle("done", j < i); li.classList.toggle("active", j === i); });
    if (i < PLAN.length - 1) planTimer = setTimeout(() => { i += 1; advance(); }, PLAN[i][2]);
  };
  advance();
}

function stopPlan(failed = false) {
  clearTimeout(planTimer);
  if (failed) {
    const active = $("timeline").querySelector("li.active");
    active?.classList.replace("active", "failed");
    $("run-meta").textContent = "Failed";
  }
}

// ---------------------------------------------------------------- render
function stepDetail(s) {
  const parts = [];
  if (s.scope) {
    const sc = s.scope;
    parts.push(`scope: ${[...sc.frameworks, ...sc.article_refs].join(", ") || "semantic only"}${sc.framework_wide ? " (framework-wide)" : ""}`);
  }
  if (s.instructions) parts.push(`instructions: ${s.instructions.join(", ")}`);
  if (s.hyde) parts.push(`HyDE: "${s.hyde.slice(0, 160)}${s.hyde.length > 160 ? "…" : ""}"`);
  if (s.dense !== undefined) parts.push(`dense ${s.dense} · sparse ${s.sparse} · fused ${s.fused} · ${s.reranked ? "reranked" : "RRF order (reranker unavailable)"} → ${s.top.length} chunks`);
  if (s.obligations !== undefined) parts.push(`${s.obligations} obligations · ${s.controls} controls · ${s.risks} risks · ${s.maps_to} MAPS_TO edges`);
  if (s.gaps !== undefined) parts.push(`${s.gaps} coverage/evidence gaps`);
  if (s.violations !== undefined) parts.push(`${s.violations} deadline violations`);
  if (s.compound !== undefined) parts.push(`${s.compound} compound obligations`);
  if (s.model) parts.push(`${s.model} · ${s.usage?.input_tokens ?? "?"} in / ${s.usage?.output_tokens ?? "?"} out tokens${s.stop_reason === "refusal" ? " · declined" : ""}`);
  if (s.passed !== undefined) parts.push(s.passed ? "all citations grounded" : `flagged: ${s.unknown.join(", ") || "low grounding"}`);
  if (s.approvals !== undefined) parts.push(`${s.approvals} approval requests created`);
  if (s.error) parts.push(`error: ${s.error}`);
  return parts.join(" | ");
}

function render(result) {
  current = result;
  stopPlan();
  const total = result.trace.reduce((a, s) => a + (s.ms || 0), 0);
  $("timeline-card").hidden = false;
  $("run-meta").textContent = `${(total / 1000).toFixed(1)} s · run ${result.run_id.slice(0, 8)}`;
  $("timeline").innerHTML = result.trace.map((s) => `
    <li class="${s.error ? "failed" : "done"}"><span class="dot"></span>
      <div><span class="agent">${escapeHtml(s.agent)}</span> <span class="action">${escapeHtml(s.action)}</span></div>
      <span class="ms">${s.ms} ms</span>
      <div class="detail">${escapeHtml(stepDetail(s))}</div></li>`).join("");

  renderAnswer(result);
  renderGaps(result.gaps);
  renderGraphCard(result.graph);
  renderContext(result);
}

function renderAnswer(result) {
  const g = result.guard;
  $("answer-card").hidden = false;
  $("guard").innerHTML = `
    <span class="badge ${g.passed ? "badge-ok" : "badge-CRITICAL"}">${g.passed ? "✓ Guard passed" : "⚠ Guard flagged"}</span>
    <span class="badge">${Math.round(g.grounding_ratio * 100)}% of claims cited</span>
    ${g.unknown_ids.length ? `<span class="badge badge-CRITICAL">${g.unknown_ids.length} unknown ID(s)</span>` : ""}
    <span class="badge badge-accent">${escapeHtml(result.model || "")}</span>`;
  $("answer").innerHTML = renderMarkdown(result.answer, g.unknown_ids) +
    (g.uncited_examples.length ? `<p class="footnote">Uncited statements: ${g.uncited_examples.map((u) => `"${escapeHtml(u)}"`).join("; ")}</p>` : "");
  $("feedback").querySelectorAll("button").forEach((b) => { b.disabled = false; });
}

function renderGaps(gaps) {
  $("gaps-card").hidden = false;
  const needApproval = gaps.filter((g) => g.approval_id).length;
  $("gaps-meta").textContent = `${gaps.length} findings · ${needApproval} awaiting human approval`;
  $("gaps-rows").innerHTML = gaps.length ? gaps.map((g) => `
    <tr>
      <td><span class="badge badge-${g.severity}">${g.severity}</span></td>
      <td><strong>${escapeHtml(`${g.framework} ${g.article_ref}`)}</strong><br>
        <span class="small">${escapeHtml(g.title)}</span><br><button type="button" class="cite" data-id="${g.obligation_id}">${g.obligation_id}</button></td>
      <td><span class="badge">${label(g.gap_type)}</span>${g.compound_with.length ? ' <span class="badge badge-accent">Compound</span>' : ""}
        <div class="small" style="margin-top:4px">${escapeHtml(g.summary)}</div>
        <div class="small muted">${escapeHtml(g.detail)}</div></td>
      <td class="num">${Number(g.risk_score).toFixed(1)}</td>
      <td>${g.approval_id ? `<a class="badge badge-primary" href="/approvals.html">Needs ${label(g.required_role)}</a>` : '<span class="muted small">Not required</span>'}</td>
    </tr>`).join("") : '<tr><td colspan="5" class="muted">No gaps found for the obligations in scope.</td></tr>';
}

function renderGraphCard(graph) {
  $("graph-card").hidden = false;
  const detail = $("node-detail");
  graphApi = renderGraph($("graph"), graph, {
    onSelect(node, neighbours) {
      if (!node) { detail.textContent = "Select a node to see its details."; return; }
      const extra = [node.title, node.status && `status: ${label(node.status)}`, node.gap && `gap: ${node.gap}`].filter(Boolean).join(" · ");
      detail.innerHTML = `<strong style="color:var(--text)">${escapeHtml(node.type)} ${escapeHtml(node.id)}</strong>, ${escapeHtml(node.label)}
        ${extra ? `<br>${escapeHtml(extra)}` : ""}<br>Connected: ${neighbours.map((n) => `<button type="button" class="cite" data-id="${n.id}">${n.id}</button>`).join("") || "none"}`;
    },
  });
}

function renderContext(result) {
  $("context-grid").hidden = false;
  $("chunks").innerHTML = result.chunks.map((c) => `
    <div class="chunk" id="chunk-${c.id}">
      <div class="chunk-meta"><span class="mono small">${escapeHtml(c.id)}</span><span class="badge">${escapeHtml(c.node_type || "")}</span>
        <span class="badge">${escapeHtml(c.framework || "")}</span>
        <span class="muted small">RRF ${c.rrf_score}${c.rerank_score != null ? ` · rerank ${Number(c.rerank_score).toFixed(3)}` : ""}</span></div>
      ${escapeHtml(c.text)}</div>`).join("");
  $("instructions").innerHTML = result.instructions.length ? result.instructions.map((i) => `
    <div class="chunk"><div class="chunk-meta"><span class="mono small">${escapeHtml(i.id)}</span><span class="badge">${label(i.domain)}</span>
      <span class="muted small">match ${Number(i.score).toFixed(3)} · success ${(Number(i.success_rate) * 100).toFixed(0)}%</span></div>
      <strong>${escapeHtml(i.title)}</strong><br><span class="muted">${escapeHtml(i.text)}</span></div>`).join("")
    : '<p class="muted">No instructions matched.</p>';
}

// Citation chips anywhere on the page -> highlight in graph, or scroll to the passage.
document.addEventListener("click", (event) => {
  const chip = event.target.closest(".cite");
  if (!chip || !graphApi) return;
  const id = chip.dataset.id;
  if (graphApi.select(id)) {
    $("graph-card").scrollIntoView({ behavior: "smooth", block: "center" });
  } else if ($(`chunk-${id}`)) {
    $(`chunk-${id}`).scrollIntoView({ behavior: "smooth", block: "center" });
  } else {
    toast(`${id} is not part of the retrieved subgraph.`, "error");
  }
});

$("feedback").addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-helpful]");
  if (!btn || !current) return;
  $("feedback").querySelectorAll("button").forEach((b) => { b.disabled = true; });
  try {
    const { updated } = await api("/codebook/feedback", { method: "POST", body: { run_id: current.run_id, helpful: btn.dataset.helpful === "true" } });
    const summary = updated.map((u) => `${u.id} ${(u.old * 100).toFixed(0)}→${(u.new * 100).toFixed(0)}%`).join(", ");
    toast(`Thanks! Updated success rates: ${summary}`, "ok", 7000);
  } catch (err) {
    toast(err.message, "error");
  }
});
