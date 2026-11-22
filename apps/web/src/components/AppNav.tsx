"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { logout } from "../lib/auth";
import { HELP } from "../lib/help";
import { MoreMenu } from "./MoreMenu";
import styles from "./dashboard.module.css";

// Top navigation for the signed-in pages (not the full-screen viewer): the project list and a new
// project, with the profile and log out folded under Account.
export function AppNav() {
  const router = useRouter();
  return (
    <nav aria-label="Main" className={styles.nav}>
      <Link href="/">Projects</Link>
      <Link href="/new">New project</Link>
      <MoreMenu label="Account" title={HELP.account}>
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
      </MoreMenu>
    </nav>
  );
}
