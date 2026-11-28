import Link from "next/link";

const LINK = { color: "#8cf" } as const;

// Back link and breadcrumb over the viewer. `shared` is null until the URL has been read: nothing
// account-related renders before that, so a share-link visitor never sees dashboard links (not even
// in the server render or the first client frame).
export function ViewerNav({ shared, manifest, viewing, standalone }: { shared: boolean | null; manifest: { id: string; name: string } | null; viewing: number | null; standalone?: boolean }) {
  if (shared === null) return null;
  if (!manifest)
    return shared ? null : (
      <div>
        <nav aria-label="Breadcrumb"><Link href="/" style={LINK}>Dashboard</Link> / Model</nav>
        <Link href="/profile" style={LINK}>Profile</Link>
        {standalone && (
          <p role="note">
            This model is not saved to a project yet. <Link href="/#unsaved" style={LINK}>Save as project</Link> on the dashboard to keep versions and share it.
          </p>
        )}
      </div>
    );
  return (
    <div>
      {shared ? (
        <span>Shared view (read-only): {manifest.name}</span>
      ) : (
        <>
          <nav aria-label="Breadcrumb">
            <Link href="/" style={LINK}>Dashboard</Link> /{" "}
            <Link href={`/projects/${manifest.id}`} style={LINK}>{manifest.name}</Link> /{" "}
            {viewing !== null ? <><Link href={`/projects/${manifest.id}#versions`} style={LINK}>Versions</Link> / Version {viewing}</> : "Viewer"}
          </nav>
          <Link href="/profile" style={LINK}>Profile</Link>
        </>
      )}
      {viewing !== null && <b role="status"> Viewing version {viewing} (read-only)</b>}
    </div>
  );
}
