import type { Issue } from "../lib/api";
import { groupIssues, LEVEL_LABEL, locations, summarize, summaryLine, type IssueGroup } from "../lib/issues";

const COLOR = { error: "#b00020", warning: "#8a6100", info: "#35516b" } as const;

function Items({ issues }: { issues: Issue[] }) {
  return (
    <ul>
      {issues.map((i, n) => {
        const locs = locations(i);
        return (
          <li key={`${n}-${i.message}`}>
            {i.message}{" "}
            {locs.length > 0 ? (
              <details style={{ display: "inline" }}>
                <summary style={{ display: "inline", cursor: "pointer" }}>
                  <small>{locs.length} {locs.length === 1 ? "location" : "locations"}</small>
                </summary>{" "}
                <small>{locs.join(", ")}</small>
              </details>
            ) : (
              <small>(no source entity)</small>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Group({ g, open }: { g: IssueGroup; open?: boolean }) {
  return (
    <details open={open} style={{ margin: "6px 0" }}>
      <summary style={{ cursor: "pointer", color: COLOR[g.level] }}>
        <strong>{LEVEL_LABEL[g.level]}:</strong> {g.title} ({g.issues.length})
      </summary>
      <p style={{ margin: "4px 0" }}>{g.help}</p>
      <Items issues={g.issues} />
      <p style={{ margin: 0 }}><small>Code: <code>{g.code}</code></small></p>
    </details>
  );
}

// Errors (blocking issues) stay open and visible; warnings and info sit in one collapsed
// accordion, grouped by what they mean. Presentation only: every issue is listed in its group.
export function IssueList({ issues }: { issues: Issue[] }) {
  if (!issues.length) return <p>No issues found.</p>;
  const groups = groupIssues(issues);
  const s = summarize(issues);
  const errors = groups.filter((g) => g.level === "error");
  const rest = groups.filter((g) => g.level !== "error");
  const restLine = summaryLine({ ...s, error: 0 });
  return (
    <div aria-label="Issues">
      <p role="status"><strong>{summaryLine(s)}</strong></p>
      {errors.length > 0 && (
        <section aria-label="Blocking issues">
          <h3>Blocking issues ({s.error}): generation is not possible until resolved</h3>
          {errors.map((g) => <Group key={`${g.level}:${g.code}`} g={g} open />)}
        </section>
      )}
      {rest.length > 0 && (
        <details aria-label="Warnings and notes">
          <summary style={{ cursor: "pointer" }}>Warnings and notes ({restLine})</summary>
          {rest.map((g) => <Group key={`${g.level}:${g.code}`} g={g} />)}
        </details>
      )}
    </div>
  );
}
