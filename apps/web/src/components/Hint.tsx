import { useId } from "react";
import styles from "./dashboard.module.css";

/** A small "?" that explains itself: the text appears on hover AND when it has keyboard focus
 *  (visible, not only a tooltip) and is announced as the description of the "?". */
export function Hint({ text }: { text: string }) {
  const id = useId();
  return (
    <span className={styles.hintWrap}>
      <span className={styles.hint} tabIndex={0} role="note" aria-label="Help" aria-describedby={id}>?</span>
      <span id={id} role="tooltip" className={styles.hintText}>{text}</span>
    </span>
  );
}
