import { authConfigured, supabase } from "./supabase.js";

const form = document.getElementById("auth-form");
const alertBox = document.getElementById("auth-alert");
const submit = document.getElementById("auth-submit");
const tabs = { signin: document.getElementById("tab-signin"), signup: document.getElementById("tab-signup") };
let mode = "signin";

const params = new URLSearchParams(location.search);
const next = (params.get("next") || "demo").replace(/[^a-z0-9_.-]/gi, "");
const destination = `/${next.endsWith(".html") ? next : `${next}.html`}`;

function show(message, kind) {
  alertBox.hidden = false;
  alertBox.className = `alert alert-${kind}`;
  alertBox.textContent = message;
}

function setMode(m) {
  mode = m;
  for (const [key, el] of Object.entries(tabs)) {
    el.setAttribute("aria-selected", String(key === m));
    el.className = `btn btn-sm ${key === m ? "btn-secondary" : "btn-ghost"}`;
  }
  submit.textContent = m === "signin" ? "Sign in" : "Create account";
  form.password.autocomplete = m === "signin" ? "current-password" : "new-password";
  alertBox.hidden = true;
}
tabs.signin.addEventListener("click", () => setMode("signin"));
tabs.signup.addEventListener("click", () => setMode("signup"));

if (!authConfigured) {
  show("Authentication is not configured: set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY and rebuild.", "error");
  submit.disabled = true;
} else {
  const { data } = await supabase.auth.getSession();
  if (data.session) location.replace(destination);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = form.email.value.trim();
  const password = form.password.value;
  if (!form.email.checkValidity() || password.length < 8) {
    show("Enter a valid email and a password of at least 8 characters.", "error");
    return;
  }
  submit.disabled = true;
  try {
    if (mode === "signin") {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      location.replace(destination);
    } else {
      const { data, error } = await supabase.auth.signUp({
        email, password, options: { emailRedirectTo: `${location.origin}${destination}` },
      });
      if (error) throw error;
      if (data.session) location.replace(destination);
      else show("Check your inbox to confirm your email, then sign in.", "ok");
    }
  } catch (err) {
    show(err.message || "Sign-in failed.", "error");
  } finally {
    submit.disabled = false;
  }
});
