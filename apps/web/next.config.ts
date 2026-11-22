import type { NextConfig } from "next";

// The browser only talks to this origin; /api/* is proxied to the FastAPI backend so the
// session cookie is first-party (SameSite=Lax). NEXT_PUBLIC_API_URL is the proxy target.
const API_TARGET = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_TARGET}/api/:path*` }];
  },
};

export default nextConfig;
