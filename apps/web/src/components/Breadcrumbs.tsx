import Link from "next/link";
import styles from "./dashboard.module.css";

export type Crumb = { label: string; href?: string };

// `Dashboard / Project / Page`. Every crumb but the last links (the parent is the way back). The last crumb is the current
// page (no link). A trail with a single crumb (the root) renders nothing.
export function Breadcrumbs({ trail }: { trail: Crumb[] }) {
  if (trail.length < 2) return null;
  return (
    <div className={styles.crumbs}>
      <nav aria-label="Breadcrumb">
        <ol className={styles.crumbList}>
          {trail.map((c, i) => (
            <li key={`${i}-${c.label}`} aria-current={i === trail.length - 1 ? "page" : undefined}>
              {c.href && i < trail.length - 1 ? <Link href={c.href}>{c.label}</Link> : c.label}
              {i < trail.length - 1 && <span aria-hidden="true"> / </span>}
            </li>
          ))}
        </ol>
      </nav>
    </div>
  );
}
