// Layered SVG view of the retrieved compliance subgraph.
// Columns follow the reasoning chain; within a column, nodes are ordered by the
// average position of their neighbours to keep edges short and crossings rare.
import { escapeHtml } from "./api.js";

const COLUMNS = ["Asset", "Risk", "Regulation", "Obligation", "Control", "Evidence"];
const COLOR = {
  Regulation: "var(--node-regulation)", Obligation: "var(--node-obligation)", Control: "var(--node-control)",
  Evidence: "var(--node-evidence)", Risk: "var(--node-risk)", Asset: "var(--node-asset)",
};
const STATUS_COLOR = { implemented: "var(--ok)", in_progress: "var(--medium)", not_started: "var(--text-muted)", failed: "var(--critical)" };
const GAP_COLOR = { CRITICAL: "var(--critical)", HIGH: "var(--high)", MEDIUM: "var(--medium)", LOW: "var(--low)" };

const NODE_W = 176, NODE_H = 34, COL_GAP = 64, ROW_GAP = 10, PAD = 44, HEAD = 26;
const truncate = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export function renderGraph(container, graph, { onSelect } = {}) {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const edges = graph.edges.filter((e) => byId.has(e.source) && byId.has(e.target));
  const neighbours = new Map(graph.nodes.map((n) => [n.id, new Set()]));
  for (const e of edges) { neighbours.get(e.source).add(e.target); neighbours.get(e.target).add(e.source); }

  // Order columns: Regulation by id, Obligation by regulation, the rest by neighbour barycentre.
  const cols = Object.fromEntries(COLUMNS.map((c) => [c, graph.nodes.filter((n) => n.type === c)]));
  const pos = new Map();
  const place = (col) => cols[col].forEach((n, i) => pos.set(n.id, i));
  cols.Regulation.sort((a, b) => a.id.localeCompare(b.id)); place("Regulation");
  const regOf = (o) => edges.find((e) => e.type === "HAS_OBLIGATION" && e.target === o.id)?.source;
  cols.Obligation.sort((a, b) => (pos.get(regOf(a)) ?? 0) - (pos.get(regOf(b)) ?? 0) || a.id.localeCompare(b.id));
  place("Obligation");
  const bary = (n, col) => {
    const ps = [...neighbours.get(n.id)].filter((id) => byId.get(id).type === col).map((id) => pos.get(id));
    return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : 1e6;
  };
  for (const [col, ref] of [["Control", "Obligation"], ["Evidence", "Control"], ["Risk", "Obligation"], ["Asset", "Risk"]]) {
    cols[col].sort((a, b) => bary(a, ref) - bary(b, ref)); place(col);
  }

  const used = COLUMNS.filter((c) => cols[c].length);
  const maxRows = Math.max(1, ...used.map((c) => cols[c].length));
  const width = PAD * 2 + used.length * NODE_W + (used.length - 1) * COL_GAP;
  const height = HEAD + PAD + maxRows * (NODE_H + ROW_GAP);
  const xy = new Map();
  used.forEach((c, ci) => {
    const offset = ((maxRows - cols[c].length) * (NODE_H + ROW_GAP)) / 2;
    cols[c].forEach((n, i) => xy.set(n.id, { x: PAD + ci * (NODE_W + COL_GAP), y: HEAD + PAD / 2 + offset + i * (NODE_H + ROW_GAP), col: ci }));
  });

  const edgeSvg = edges.map((e) => {
    const a = xy.get(e.source), b = xy.get(e.target);
    const cls = `edge edge-${e.type}`;
    if (a.col === b.col) { // MAPS_TO within the obligation column: arc to the left
      const x = a.x, y1 = a.y + NODE_H / 2, y2 = b.y + NODE_H / 2, bulge = 24 + Math.abs(y2 - y1) * 0.18;
      return `<path class="${cls}" data-a="${e.source}" data-b="${e.target}" d="M${x},${y1} C${x - bulge},${y1} ${x - bulge},${y2} ${x},${y2}"/>`;
    }
    const [l, r] = a.col < b.col ? [a, b] : [b, a];
    const x1 = l.x + NODE_W, y1 = l.y + NODE_H / 2, x2 = r.x, y2 = r.y + NODE_H / 2, mid = (x1 + x2) / 2;
    return `<path class="${cls}" data-a="${e.source}" data-b="${e.target}" d="M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}"/>`;
  }).join("");

  const heads = used.map((c, ci) => `<text class="col-head" x="${PAD + ci * (NODE_W + COL_GAP) + NODE_W / 2}" y="18" text-anchor="middle">${c}</text>`).join("");

  const nodeSvg = graph.nodes.map((n) => {
    const p = xy.get(n.id);
    const marker = n.gap ? `<circle cx="${NODE_W - 12}" cy="${NODE_H / 2}" r="5" fill="${GAP_COLOR[n.gap]}"><title>${n.gap} gap</title></circle>`
      : n.status ? `<circle cx="${NODE_W - 12}" cy="${NODE_H / 2}" r="5" fill="${STATUS_COLOR[n.status] || "var(--text-muted)"}"><title>${n.status.replace(/_/g, " ")}</title></circle>` : "";
    return `<g class="node" tabindex="0" data-id="${n.id}" transform="translate(${p.x},${p.y})" aria-label="${escapeHtml(`${n.type} ${n.id}: ${n.label}`)}">
      <rect width="${NODE_W}" height="${NODE_H}" rx="8" class="node-box" style="--c:${COLOR[n.type]}"/>
      <rect width="4" height="${NODE_H - 12}" x="6" y="6" rx="2" fill="${COLOR[n.type]}"/>
      <text x="16" y="14" class="node-id">${escapeHtml(n.id)}</text>
      <text x="16" y="27" class="node-label">${escapeHtml(truncate(n.label, marker ? 24 : 27))}</text>
      ${marker}<title>${escapeHtml(`${n.id} · ${n.title || n.label}`)}</title>
    </g>`;
  }).join("");

  container.innerHTML = `<svg class="graph-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img"
    aria-label="Retrieved compliance subgraph with ${graph.nodes.length} nodes">${heads}<g>${edgeSvg}</g><g>${nodeSvg}</g></svg>`;

  const svg = container.querySelector("svg");
  let selected = null;
  const select = (id, { scroll = false } = {}) => {
    selected = id;
    const keep = id ? new Set([id, ...neighbours.get(id)]) : null;
    svg.classList.toggle("has-selection", Boolean(id));
    svg.querySelectorAll(".node").forEach((g) => {
      g.classList.toggle("dim", Boolean(keep) && !keep.has(g.dataset.id));
      g.classList.toggle("selected", g.dataset.id === id);
    });
    svg.querySelectorAll(".edge").forEach((p) => p.classList.toggle("lit", Boolean(id) && (p.dataset.a === id || p.dataset.b === id)));
    if (id && scroll) {
      const p = xy.get(id);
      container.scrollTo({ left: Math.max(0, p.x - container.clientWidth / 2 + NODE_W / 2), top: Math.max(0, p.y - container.clientHeight / 2), behavior: "smooth" });
    }
    if (onSelect) onSelect(id ? byId.get(id) : null, id ? [...neighbours.get(id)].map((x) => byId.get(x)) : []);
  };
  svg.querySelectorAll(".node").forEach((g) => {
    const toggle = () => select(selected === g.dataset.id ? null : g.dataset.id);
    g.addEventListener("click", toggle);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
  });

  return { select: (id) => (byId.has(id) ? (select(id, { scroll: true }), true) : false), clear: () => select(null) };
}
