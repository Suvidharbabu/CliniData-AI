import { escapeHtml } from "./api.js";
import { supabase } from "./supabase.js";

const LINKS = [
  ["platform", "Platform"],
  ["architecture", "Architecture"],
  ["agents", "Agents"],
  ["codebook", "Codebook"],
  ["security", "Security"],
  ["roadmap", "Roadmap"],
  ["contact", "Contact"],
];

export const LOGO = `
<svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
  <rect width="32" height="32" rx="8" fill="var(--primary)"/>
  <path d="M10 21.5 16 10l6 11.5M10 21.5h12" stroke="var(--on-primary)" stroke-width="1.6" fill="none" stroke-linejoin="round"/>
  <circle cx="16" cy="10" r="3" fill="var(--on-primary)"/>
  <circle cx="10" cy="21.5" r="3" fill="var(--on-primary)"/>
  <circle cx="22" cy="21.5" r="3" fill="var(--on-primary)"/>
</svg>`;

const SUN = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MOON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>`;
const MENU = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>`;

function currentPage() {
  const p = location.pathname.replace(/^\/|\.html$/g, "");
  return p === "" ? "index" : p;
}

function storedTheme() {
  try { return localStorage.getItem("theme"); } catch { return null; }
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}

function renderHeader() {
  const page = currentPage();
  const links = LINKS.map(([href, text]) =>
    `<li><a href="/${href}.html"${page === href ? ' aria-current="page"' : ""}>${text}</a></li>`).join("");
  const header = document.createElement("header");
  header.className = "site-header";
  header.innerHTML = `
    <nav class="container nav" aria-label="Main">
      <a class="brand" href="/">${LOGO}<span>CliniData <span class="ai">AI</span></span></a>
      <ul class="nav-links" id="nav-links">${links}<li class="mobile-only"><a href="/demo.html">Live demo</a></li></ul>
      <div class="nav-actions">
        <span class="user-chip" id="user-chip"></span>
        <button class="icon-btn" id="theme-toggle" type="button" aria-label="Toggle dark mode"></button>
        <a class="btn btn-primary btn-sm" id="demo-link" href="/demo.html">Try the demo</a>
        <button class="icon-btn menu-toggle" id="menu-toggle" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="nav-links">${MENU}</button>
      </div>
    </nav>`;
  document.body.prepend(header);

  const themeBtn = header.querySelector("#theme-toggle");
  const paintThemeBtn = () => { themeBtn.innerHTML = isDark() ? SUN : MOON; };
  paintThemeBtn();
  themeBtn.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("theme", next); } catch { /* storage unavailable */ }
    paintThemeBtn();
  });

  const menuBtn = header.querySelector("#menu-toggle");
  const list = header.querySelector("#nav-links");
  menuBtn.addEventListener("click", () => {
    const open = list.classList.toggle("open");
    menuBtn.setAttribute("aria-expanded", String(open));
  });
}

function renderFooter() {
  const footer = document.createElement("footer");
  footer.className = "site-footer";
  footer.innerHTML = `
    <div class="container">
      <div class="footer-grid">
        <div>
          <a class="brand" href="/">${LOGO}<span>CliniData <span class="ai">AI</span></span></a>
          <p class="muted small" style="margin-top:12px;max-width:36ch">Graph RAG, hybrid retrieval and agentic AI for healthcare and life-sciences compliance.</p>
        </div>
        <div><h4>Platform</h4><ul>
          <li><a href="/platform.html">Modules</a></li><li><a href="/architecture.html">Architecture</a></li>
          <li><a href="/agents.html">Agents</a></li><li><a href="/codebook.html">Codebook</a></li></ul></div>
        <div><h4>Trust</h4><ul>
          <li><a href="/security.html">Security &amp; governance</a></li><li><a href="/roadmap.html">Roadmap</a></li></ul></div>
        <div><h4>Get started</h4><ul>
          <li><a href="/demo.html">Live demo</a></li><li><a href="/approvals.html">Approvals</a></li>
          <li><a href="/contact.html">Request a walkthrough</a></li></ul></div>
      </div>
      <p class="disclaimer">CliniData AI is a demonstration project. The demo tenant "Meridian Clinical Research" and its controls are fictional,
      regulation texts are paraphrased summaries, and performance figures are design targets from the platform specification, not measured results.
      Nothing on this site is legal or regulatory advice. &copy; ${new Date().getFullYear()} CliniData AI.</p>
    </div>`;
  document.body.append(footer);
}

async function renderAuthState() {
  const chip = document.getElementById("user-chip");
  if (!supabase || !chip) return;
  const paint = (session) => {
    if (session) {
      chip.innerHTML = `${escapeHtml(session.user.email)} · <a href="#" id="sign-out">Sign out</a>`;
      chip.querySelector("#sign-out").addEventListener("click", async (e) => {
        e.preventDefault();
        await supabase.auth.signOut();
        location.href = "/";
      });
    } else {
      chip.innerHTML = `<a href="/login.html">Sign in</a>`;
    }
  };
  const { data } = await supabase.auth.getSession();
  paint(data.session);
  supabase.auth.onAuthStateChange((_event, session) => paint(session));
}

applyTheme(storedTheme());
renderHeader();
renderFooter();
renderAuthState();
