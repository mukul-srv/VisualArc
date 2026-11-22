"use client";

import { useParams } from "next/navigation";
import { ProjectView } from "@/components/ProjectView";
import { RequireAuth } from "@/components/RequireAuth";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <RequireAuth>
      <ProjectView id={id} />
    </RequireAuth>
  );
}
