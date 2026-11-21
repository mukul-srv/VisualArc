import type { ReactNode } from "react";
import { RequireAuth } from "@/components/RequireAuth";

export default function ViewerLayout({ children }: { children: ReactNode }) {
  return <RequireAuth>{children}</RequireAuth>;
}
