import { send } from "./api";

type Fetch = typeof fetch;
export type User = { id: string; email: string; display_name: string; has_password: boolean };
export type Providers = { github: boolean; google: boolean };
export const MIN_PASSWORD = 10; // mirrors the API rule; the API is the authority

// Same-site relative paths only, so `?next=` cannot send the user off-site.
export const safeNext = (next: string | null | undefined): string =>
  next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";

export const loginUrl = (pathname: string, search = ""): string => {
  const next = safeNext(pathname + search);
  return next === "/" ? "/login" : `/login?next=${encodeURIComponent(next)}`;
};

export const oauthUrl = (provider: keyof Providers, next: string): string =>
  `/api/v1/auth/oauth/${provider}/login?next=${encodeURIComponent(safeNext(next))}`;

const call = (path: string, method: string, body: unknown, f: Fetch) =>
  f(`/api/v1/auth${path}`, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const login = (email: string, password: string, f: Fetch = fetch) =>
  send<User>(() => call("/login", "POST", { email, password }, f));

export const register = (email: string, password: string, display_name: string, f: Fetch = fetch) =>
  send<User>(() => call("/register", "POST", { email, password, ...(display_name ? { display_name } : {}) }, f));

export const me = (f: Fetch = fetch) => send<User>(() => f("/api/v1/auth/me", { credentials: "include" }));

export const logout = async (f: Fetch = fetch) => {
  try {
    await call("/logout", "POST", undefined, f);
  } catch {
    /* offline: the redirect to /login still happens, the cookie expires server-side */
  }
};

export const updateProfile = (
  body: { display_name?: string; current_password?: string; new_password?: string },
  f: Fetch = fetch,
) => send<User>(() => call("/profile", "PATCH", body, f));

export const getProviders = async (f: Fetch = fetch): Promise<Providers> => {
  try {
    const res = await f("/api/v1/auth/providers", { credentials: "include" });
    if (res.ok) return await res.json();
  } catch {
    /* API down: show no OAuth buttons */
  }
  return { github: false, google: false };
};

// Client-side form checks (instant feedback only; the API re-validates).
export const credentialErrors = (email: string, password: string, mode: "login" | "register"): string[] => {
  const errors: string[] = [];
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) errors.push("Enter a valid email address.");
  if (!password) errors.push("Enter your password.");
  else if (mode === "register" && password.length < MIN_PASSWORD)
    errors.push(`Password must be at least ${MIN_PASSWORD} characters.`);
  return errors;
};
