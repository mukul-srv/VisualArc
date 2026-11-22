"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { loginUrl, me, type User } from "../lib/auth";

// Client-side gate: renders children only for a signed-in user, else sends them to
// /login?next=<here>. The API enforces auth itself; this is just the UX redirect.
// Shown when /me cannot be loaded (API down, 5xx): an explanation and a way to try again.
export function RetryNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert">
      <p>Could not check your sign-in: {message}</p>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

// `allowShare`: a `?share=<token>` link opens the page without sign-in (the API checks the token).
export function RequireAuth({ children, onUser, allowShare }: { children: ReactNode; onUser?: (u: User) => void; allowShare?: boolean }) {
  const router = useRouter();
  const [ok, setOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (allowShare && new URLSearchParams(window.location.search).has("share")) return queueMicrotask(() => setOk(true));
    me().then((r) => {
      if (r.ok) {
        onUser?.(r);
        setOk(true);
      } else if (r.kind === "unauthorized") {
        router.replace(loginUrl(window.location.pathname, window.location.search));
      } else {
        setError(r.message);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run only on retry
  }, [attempt]);
  if (ok) return <>{children}</>;
  if (error) {
    return (
      <RetryNotice
        message={error}
        onRetry={() => {
          setError(null);
          setAttempt(attempt + 1);
        }}
      />
    );
  }
  return <p role="status">Checking sign-in…</p>;
}
