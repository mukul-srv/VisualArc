import type { Issue } from "../lib/api";
import { splitIssues } from "../lib/params";

// Blocking and warnings are distinct in text and structure (never colour alone).
export function IssueList({ issues }: { issues: Issue[] }) {
  const { blocking, warnings } = splitIssues(issues);
  if (!issues.length) return <p>No issues found.</p>;
  const item = (i: Issue, label: string, color: string) => (
    <li key={`${i.code}-${i.message}`} style={{ color }}>
      <strong>{label}</strong> <code>{i.code}</code>: {i.message}
    </li>
  );
  return (
    <div>
      {blocking.length > 0 && (
        <section aria-label="Blocking issues">
          <h3>Blocking issues ({blocking.length}): generation is not possible until resolved</h3>
          <ul>{blocking.map((i) => item(i, "BLOCKING", "#b00020"))}</ul>
        </section>
      )}
      {warnings.length > 0 && (
        <section aria-label="Warnings">
          <h3>Warnings ({warnings.length})</h3>
          <ul>{warnings.map((i) => item(i, "warning", "#8a6100"))}</ul>
        </section>
      )}
    </div>
  );
}
