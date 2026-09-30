// Grouped horizontal bar chart: retrieval precision@10 and recall@10 per configuration.
// Values are design targets from the ECRIP specification.
const DATA = [
  { config: "Dense only (Pinecone)", precision: 74, recall: 69, latency: "~120 ms" },
  { config: "Sparse only (BM25)", precision: 61, recall: 58, latency: "~80 ms" },
  { config: "Hybrid (RRF, no rerank)", precision: 84, recall: 79, latency: "~200 ms" },
  { config: "Hybrid + rerank", precision: 91, recall: 86, latency: "~380 ms" },
];
const SERIES = [
  { key: "precision", label: "Precision@10", color: "var(--series-1)" },
  { key: "recall", label: "Recall@10", color: "var(--series-2)" },
];

const W = 440, LABEL_W = 150, RIGHT = 40, BAR_H = 14, GAP = 2, ROW_H = 2 * BAR_H + GAP + 22, TOP = 8, AXIS_H = 24;
const H = TOP + DATA.length * ROW_H + AXIS_H;
const plotW = W - LABEL_W - RIGHT;
const x = (v) => (v / 100) * plotW;

// Bar with square baseline end and 4px rounded data end.
function barPath(x0, y, w, h, r = 4) {
  r = Math.min(r, w, h / 2);
  return `M${x0},${y} H${x0 + w - r} Q${x0 + w},${y} ${x0 + w},${y + r} V${y + h - r} Q${x0 + w},${y + h} ${x0 + w - r},${y + h} H${x0} Z`;
}

export function renderBenchChart(root) {
  const grid = [0, 25, 50, 75, 100].map((t) => `
    <line class="grid-line" x1="${LABEL_W + x(t)}" x2="${LABEL_W + x(t)}" y1="${TOP}" y2="${H - AXIS_H}"/>
    <text x="${LABEL_W + x(t)}" y="${H - 6}" text-anchor="middle">${t}%</text>`).join("");

  const rows = DATA.map((d, i) => {
    const y0 = TOP + i * ROW_H + 8;
    const bars = SERIES.map((s, j) => {
      const y = y0 + j * (BAR_H + GAP);
      const v = d[s.key];
      return `<g class="bar" tabindex="0" data-i="${i}" data-s="${j}" aria-label="${d.config}, ${s.label} ${v}%">
        <rect x="${LABEL_W}" y="${y - 3}" width="${plotW}" height="${BAR_H + 4}" fill="transparent"/>
        <path d="${barPath(LABEL_W, y, x(v), BAR_H)}" fill="${s.color}"/>
        <text class="val" x="${LABEL_W + x(v) + 6}" y="${y + BAR_H - 3}">${v}%</text>
      </g>`;
    }).join("");
    return `<text x="${LABEL_W - 10}" y="${y0 + BAR_H + 4}" text-anchor="end" style="fill:var(--text)">${d.config}</text>${bars}`;
  }).join("");

  root.innerHTML = `
    <div class="legend">${SERIES.map((s) => `<span style="--swatch:${s.color}">${s.label}</span>`).join("")}</div>
    <div style="position:relative">
      <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Retrieval precision and recall by configuration">${grid}${rows}</svg>
      <div class="chart-tip" hidden></div>
    </div>`;

  const tip = root.querySelector(".chart-tip");
  const svg = root.querySelector("svg");
  const show = (g) => {
    const d = DATA[+g.dataset.i];
    const s = SERIES[+g.dataset.s];
    tip.innerHTML = `<strong>${d.config}</strong><br>${s.label}: ${d[s.key]}%<br><span class="muted">Latency ${d.latency}</span>`;
    tip.hidden = false;
    const box = g.getBoundingClientRect(), host = svg.getBoundingClientRect();
    tip.style.left = `${Math.min(box.right - host.left + 8, host.width - 190)}px`;
    tip.style.top = `${box.top - host.top - 8}px`;
    root.querySelectorAll(".bar").forEach((b) => b.style.opacity = b === g ? "1" : "0.45");
  };
  const hide = () => { tip.hidden = true; root.querySelectorAll(".bar").forEach((b) => b.style.opacity = "1"); };
  root.querySelectorAll(".bar").forEach((g) => {
    g.addEventListener("pointerenter", () => show(g));
    g.addEventListener("focus", () => show(g));
    g.addEventListener("pointerleave", hide);
    g.addEventListener("blur", hide);
  });
}
