import { ProfileForm } from "@/components/ProfileForm";
import { RequireAuth } from "@/components/RequireAuth";

export default function ProfilePage() {
  return (
    <RequireAuth>
      <ProfileForm />
    </RequireAuth>
  );
}
