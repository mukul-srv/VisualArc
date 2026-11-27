import type { Metadata } from "next";
import { ProfileForm } from "@/components/ProfileForm";
import { RequireAuth } from "@/components/RequireAuth";

export const metadata: Metadata = { title: "Profile" };

export default function ProfilePage() {
  return (
    <RequireAuth>
      <ProfileForm />
    </RequireAuth>
  );
}
