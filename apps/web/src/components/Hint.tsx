import styles from "./dashboard.module.css";

/** A small "?" that explains itself on hover or keyboard focus (the title pattern used for the
 *  standalone-model label). Decorative for screen readers: the text is also the aria-label. */
export function Hint({ text }: { text: string }) {
  return (
    <span className={styles.hint} title={text} aria-label={text} role="note" tabIndex={0}>?</span>
  );
}
