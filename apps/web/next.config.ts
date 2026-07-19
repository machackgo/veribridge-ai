import type { NextConfig } from "next";
import path from "node:path";

// The web app lives at apps/web but imports the shared Website Proof recorder
// contract from packages/shared (a sibling of apps/). Turbopack refuses to
// resolve modules outside its root, so pin the root to the monorepo root
// (two levels up from this config file) rather than apps/web.
const monorepoRoot = path.resolve(import.meta.dirname, "..", "..");

const nextConfig: NextConfig = {
  turbopack: {
    root: monorepoRoot,
  },
};

export default nextConfig;
