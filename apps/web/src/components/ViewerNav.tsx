import Link from "next/link";

const LINK = { color: "#8cf" } as const;

// Back link and breadcrumb over the viewer. `shared` is null until the URL has been read: nothing
// account-related renders before that, so a share-link visitor never sees dashboard links (not even
// in the server render or the first client frame).
export function ViewerNav({ shared, manifest, viewing }: { shared: boolean | null; manifest: { id: string; name: string } | null; viewing: number | null }) {
  if (shared === null) return null;
  if (!manifest)
    return shared ? null : (
      <div>
        <Link href="/" style={LINK}>&larr; Back to dashboard</Link>
        <nav aria-label="Breadcrumb"><Link href="/" style={LINK}>Dashboard</Link> / Model</nav>
      </div>
    );
  return (
    <div>
      {shared ? (
        <span>Shared view (read-only): {manifest.name}</span>
      ) : (
        <>
          <Link href={viewing !== null ? `/projects/${manifest.id}#versions` : `/projects/${manifest.id}`} style={LINK}>
            &larr; Back to {viewing !== null ? "versions" : "project"}
          </Link>
          <nav aria-label="Breadcrumb">
            <Link href="/" style={LINK}>Dashboard</Link> /{" "}
            <Link href={`/projects/${manifest.id}`} style={LINK}>{manifest.name}</Link> /{" "}
            {viewing !== null ? <><Link href={`/projects/${manifest.id}#versions`} style={LINK}>Versions</Link> / Version {viewing}</> : "Viewer"}
          </nav>
        </>
      )}
      {viewing !== null && <b role="status"> Viewing version {viewing} (read-only)</b>}
    </div>
  );
}
