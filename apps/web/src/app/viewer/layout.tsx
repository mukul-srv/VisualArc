import type { Metadata } from "next";
import type { ReactNode } from "react";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = { title: "Viewer" };

export default function ViewerLayout({ children }: { children: ReactNode }) {
  return <RequireAuth allowShare>{children}</RequireAuth>;
}
