import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const authConfigured = Boolean(url && key);

export const supabase = authConfigured
  ? createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true } })
  : null;

export async function getSession() {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session;
}

/** Redirect to the login page when there is no session. Returns the session otherwise. */
export async function requireSession() {
  const session = await getSession();
  if (!session) {
    const next = encodeURIComponent(location.pathname.replace(/^\//, "") || "demo");
    location.href = `/login.html?next=${next}`;
    return null;
  }
  return session;
}
