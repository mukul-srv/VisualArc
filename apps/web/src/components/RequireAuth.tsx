"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { loginUrl, me, type User } from "@/lib/auth";

// Client-side gate: renders children only for a signed-in user, else sends them to
// /login?next=<here>. The API enforces auth itself; this is just the UX redirect.
export function RequireAuth({ children, onUser }: { children: ReactNode; onUser?: (u: User) => void }) {
  const router = useRouter();
  const [ok, setOk] = useState(false);
  useEffect(() => {
    me().then((r) => {
      if (r.ok) {
        onUser?.(r);
        setOk(true);
      } else if (r.kind === "unauthorized") {
        router.replace(loginUrl(window.location.pathname, window.location.search));
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
  }, []);
  return ok ? <>{children}</> : <p role="status">Checking sign-in…</p>;
}
