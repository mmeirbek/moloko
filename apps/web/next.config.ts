import path from "node:path";

import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

// Dev only: `next dev` forwards /api/* to the FastAPI server. In production the
// reverse proxy (Caddy) routes /api/* and /ws/* to the backend instead.
const apiProxyTarget = process.env.API_PROXY_TARGET;

const nextConfig: NextConfig = {
  output: "standalone",
  // Monorepo: trace dependencies from the repository root.
  outputFileTracingRoot: path.join(__dirname, "../.."),
  poweredByHeader: false,
  reactStrictMode: true,
  // The subagents' office is gone (2026-11-02): old links open the run's task or the office.
  async redirects() {
    return [
      {
        source: "/office/subagents",
        has: [{ type: "query", key: "run", value: "(?<run>[0-9a-f-]{36})" }],
        destination: "/runs/:run",
        permanent: false,
      },
      { source: "/office/subagents", destination: "/office/agents", permanent: false },
    ];
  },
  async rewrites() {
    if (!apiProxyTarget) return [];
    return [{ source: "/api/:path*", destination: `${apiProxyTarget}/api/:path*` }];
  },
};

export default withNextIntl(nextConfig);
