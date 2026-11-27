"use client";

import Link from "next/link";

export default function ErrorPage({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <main>
      <h1>Something went wrong</h1>
      <p role="alert">Try again, or go back to your projects.</p>
      <button type="button" onClick={() => retry()}>Try again</button>{" "}
      <Link href="/">Back to projects</Link>
    </main>
  );
}
