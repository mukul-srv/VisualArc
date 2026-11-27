import Link from "next/link";

export default function NotFound() {
  return (
    <main>
      <h1>Page not found</h1>
      <p>This page does not exist or you do not have access.</p>
      <Link href="/">Back to projects</Link>
    </main>
  );
}
