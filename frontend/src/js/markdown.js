import { escapeHtml } from "./api.js";

const ID_RE = /\b(?:OBL|CTL|REG|RSK|AST|EVD|ENT|POL)-[A-Z0-9][A-Z0-9-]*\b/g;

function inline(text, unknown) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
  // Citations: [OBL-X] or [CTL-A, EVD-B] -> clickable chips
  html = html.replace(/\[([^\[\]]+)\]/g, (match, inner) => {
    const ids = inner.match(ID_RE);
    if (!ids) return match;
    return ids.map((id) => {
      const bad = unknown.has(id);
      return `<button type="button" class="cite${bad ? " cite-bad" : ""}" data-id="${id}" title="${bad ? "Not in the retrieved subgraph" : "Show in graph"}">${id}</button>`;
    }).join("");
  });
  return html;
}

/** Minimal, safe markdown: headings, bullet/numbered lists, bold, italics, code, citations. */
export function renderMarkdown(md, unknownIds = []) {
  const unknown = new Set(unknownIds);
  const out = [];
  let list = null;
  let para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "), unknown)}</p>`); para = []; } };
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };

  for (const raw of String(md).split(/\r?\n/)) {
    const line = raw.trim();
    let m;
    if (!line) { flushPara(); closeList(); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flushPara(); closeList();
      const level = Math.min(4, m[1].length + 1);
      out.push(`<h${level}>${inline(m[2], unknown)}</h${level}>`);
    } else if ((m = line.match(/^[-*+]\s+(.*)$/)) || (m = line.match(/^\d+[.)]\s+(.*)$/))) {
      flushPara();
      const type = /^\d/.test(line) ? "ol" : "ul";
      if (list !== type) { closeList(); out.push(`<${type}>`); list = type; }
      out.push(`<li>${inline(m[1], unknown)}</li>`);
    } else {
      closeList();
      para.push(line);
    }
  }
  flushPara(); closeList();
  return out.join("\n");
}
