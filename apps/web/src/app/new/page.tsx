import { RequireAuth } from "@/components/RequireAuth";
import { UploadFlow } from "@/components/UploadFlow";

export default function NewProject() {
  return (
    <RequireAuth>
      <UploadFlow />
    </RequireAuth>
  );
}
