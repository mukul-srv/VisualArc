"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { credentialErrors, getProviders, login, oauthUrl, register, safeNext, type Providers } from "../lib/auth";
import styles from "./auth.module.css";

// OAuth callback error codes (?error=) -> text; anything else is shown as given.
export const OAUTH_ERRORS: Record<string, string> = {
  email_exists: "An account with this email exists. Sign in with your password.",
  no_verified_email: "The provider did not share a verified email address.",
};

const LABEL = { github: "GitHub", google: "Google" } as const;

// Presentational: provider buttons only for configured providers.
export function AuthFormView(props: {
  mode: "login" | "register";
  providers: Providers;
  next: string;
  errors: string[];
  busy?: boolean;
  onSubmit?: (v: { email: string; password: string; name: string }) => void;
}) {
  const { mode, providers, next, errors, busy, onSubmit } = props;
  const [v, setV] = useState({ email: "", password: "", name: "" });
  const title = mode === "login" ? "Log in" : "Create account";
  const other = mode === "login" ? "register" : "login";
  const suffix = next === "/" ? "" : `?next=${encodeURIComponent(next)}`;
  return (
    <main className={styles.card}>
      <h1>{title}</h1>
      {errors.length > 0 && (
        <ul role="alert" className={styles.errors}>
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit?.(v);
        }}
      >
        {mode === "register" && (
          <label>
            Display name (optional)
            <input name="name" autoComplete="name" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
          </label>
        )}
        <label>
          Email
          <input name="email" type="email" autoComplete="email" required value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={mode === "register" ? 10 : undefined}
            value={v.password}
            onChange={(e) => setV({ ...v, password: e.target.value })}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Please wait…" : title}
        </button>
      </form>
      {(Object.keys(LABEL) as (keyof Providers)[])
        .filter((p) => providers[p])
        .map((p) => (
          <a key={p} className={styles.provider} href={oauthUrl(p, next)}>
            Continue with {LABEL[p]}
          </a>
        ))}
      <p>
        {mode === "login" ? "No account? " : "Already registered? "}
        <a href={`/${other}${suffix}`}>{other === "register" ? "Create one" : "Log in"}</a>
      </p>
    </main>
  );
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [providers, setProviders] = useState<Providers>({ github: false, google: false });
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [next, setNext] = useState("/");

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read once from the URL
    setNext(safeNext(q.get("next")));
    const oauthError = q.get("error");
    if (oauthError) setErrors([OAUTH_ERRORS[oauthError] ?? oauthError]);
    getProviders().then(setProviders);
  }, []);

  async function submit({ email, password, name }: { email: string; password: string; name: string }) {
    const bad = credentialErrors(email, password, mode);
    if (bad.length) return setErrors(bad);
    setBusy(true);
    const r = mode === "login" ? await login(email, password) : await register(email, password, name.trim());
    if (r.ok) return router.replace(next);
    setBusy(false);
    setErrors([r.message]);
  }

  return <AuthFormView mode={mode} providers={providers} next={next} errors={errors} busy={busy} onSubmit={submit} />;
}
