import { PROVENANCE_LABEL } from "../lib/selection";

/** Said once per page: what the bracketed notes next to values mean. */
export function ProvenanceNote() {
  return (
    <details style={{ marginBottom: 8 }}>
      <summary>What does this mean?</summary>
      <small>
        Notes in brackets say where a value comes from: &quot;{PROVENANCE_LABEL.source_extracted}&quot; was read from your file;
        &quot;{PROVENANCE_LABEL.defaulted}&quot; is a typical value we used; &quot;{PROVENANCE_LABEL.inferred}&quot; was not drawn; edits are marked as yours.
      </small>
    </details>
  );
}
