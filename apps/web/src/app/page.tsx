import { Dashboard } from "@/components/Dashboard";
import { RequireAuth } from "@/components/RequireAuth";

export default function Home() {
  return (
    <RequireAuth>
      <Dashboard />
    </RequireAuth>
  );
}
