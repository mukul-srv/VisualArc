"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { logout } from "../lib/auth";
import styles from "./dashboard.module.css";

// Top navigation for the signed-in pages (not the full-screen viewer): one click to the project
// list, a new project, the profile, and log out.
export function AppNav() {
  const router = useRouter();
  return (
    <nav aria-label="Main" className={styles.nav}>
      <Link href="/">Projects</Link>
      <Link href="/new">New project</Link>
      <Link href="/profile">Profile</Link>
      <button
        type="button"
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
      >
        Log out
      </button>
    </nav>
  );
}
