"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { RequireAuth } from "@/components/RequireAuth";
import { UploadFlow } from "@/components/UploadFlow";
import { uploadKey } from "@/lib/upload-state";

// Keyed by the query string: /new and /new?project=<id> are different pages with different state,
// so moving between them (or to another project) remounts the flow with an empty file, form and target.
function Keyed() {
  return <UploadFlow key={uploadKey(useSearchParams().toString())} />;
}

export default function NewProject() {
  return (
    <RequireAuth>
      <Suspense fallback={null}>
        <Keyed />
      </Suspense>
    </RequireAuth>
  );
}
