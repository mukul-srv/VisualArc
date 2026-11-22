"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Breadcrumbs } from "./Breadcrumbs";
import { logout, me, MIN_PASSWORD, updateProfile, type User } from "../lib/auth";
import { RetryNotice } from "./RequireAuth";
import styles from "./auth.module.css";

export function ProfileForm() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [name, setName] = useState("");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    me().then((r) => {
      if (!r.ok) return setLoadError(r.message);
      setUser(r);
      setName(r.display_name);
    });
  }, [attempt]);

  async function save(body: Parameters<typeof updateProfile>[0], done: string) {
    const r = await updateProfile(body);
    if (r.ok) {
      setUser(r);
      setPw({ current: "", next: "" });
    }
    setMsg({ ok: r.ok, text: r.ok ? done : r.message });
  }

  if (!user && loadError) {
    return (
      <RetryNotice
        message={loadError}
        onRetry={() => {
          setLoadError(null);
          setAttempt(attempt + 1);
        }}
      />
    );
  }
  if (!user) return <p role="status">Loading…</p>;
  return (
    <main className={styles.card}>
      <Breadcrumbs trail={[{ label: "Dashboard", href: "/" }, { label: "Profile" }]} />
      <h1>Profile</h1>
      <p>Signed in as {user.email}</p>
      {msg && (
        <p role={msg.ok ? "status" : "alert"} className={msg.ok ? undefined : styles.errors}>
          {msg.text}
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save({ display_name: name.trim() }, "Name updated.");
        }}
      >
        <label>
          Display name
          <input value={name} required maxLength={100} onChange={(e) => setName(e.target.value)} />
        </label>
        <button type="submit">Save name</button>
      </form>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save({ current_password: pw.current || undefined, new_password: pw.next }, "Password changed.");
        }}
      >
        <h2>Change password</h2>
        {user.has_password && (
          <label>
            Current password
            <input type="password" autoComplete="current-password" required value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          </label>
        )}
        <label>
          New password (min {MIN_PASSWORD} characters)
          <input type="password" autoComplete="new-password" required minLength={MIN_PASSWORD} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
        </label>
        <button type="submit">Change password</button>
      </form>
      <button
        type="button"
        className={styles.provider}
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
      >
        Log out
      </button>
    </main>
  );
}
