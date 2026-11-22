import Link from "next/link";
import styles from "./dashboard.module.css";

export type Crumb = { label: string; href?: string };

// `Dashboard / Project / Page` plus a Back link to the parent crumb. The last crumb is the current
// page (no link). A trail with a single crumb (the root) renders nothing.
export function Breadcrumbs({ trail }: { trail: Crumb[] }) {
  if (trail.length < 2) return null;
  const parent = [...trail.slice(0, -1)].reverse().find((c) => c.href);
  return (
    <div className={styles.crumbs}>
      {parent?.href && <Link href={parent.href}>&larr; Back to {parent.label}</Link>}
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
