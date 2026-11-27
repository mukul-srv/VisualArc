import type { Metadata } from "next";
import { Dashboard } from "@/components/Dashboard";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = { title: { absolute: "My projects | Visual Arc" } };

export default function Home() {
  return (
    <RequireAuth>
      <Dashboard />
    </RequireAuth>
  );
}
