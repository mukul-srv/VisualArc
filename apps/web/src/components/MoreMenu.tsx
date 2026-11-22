import type { ReactNode } from "react";
import styles from "./dashboard.module.css";

/** Rarely used actions behind one control, collapsed by default (a native <details>, so it works with
 *  the keyboard and without script). Nothing is removed: every action is one click further away. */
export function MoreMenu({ label = "More", title, children }: { label?: string; title?: string; children: ReactNode }) {
  return (
    <details className={styles.more}>
      <summary title={title}>{label}</summary>
      <span className={styles.moreBody}>{children}</span>
    </details>
  );
}
