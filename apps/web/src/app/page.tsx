import { RequireAuth } from "@/components/RequireAuth";
import { UploadFlow } from "@/components/UploadFlow";

export default function Home() {
  return (
    <RequireAuth>
      <UploadFlow />
    </RequireAuth>
  );
}
