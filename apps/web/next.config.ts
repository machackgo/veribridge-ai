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
  // The old /recruiter/* prototype console (fabricated sample candidates) was
  // removed in favor of the real Recruiter V1 flow. Old deep links land on the
  // real surfaces: the entry page handles auth state, and the workspace is the
  // one production recruiter destination. Temporary (307) redirects so the
  // paths stay reclaimable.
  // Static launch-film media is content-addressed by filename and never
  // rewritten in place, so it can be cached hard. Next.js's default for
  // public/ is `max-age=0, must-revalidate`, which makes every repeat view of
  // a 70 MB film re-validate — and range requests reuse a partial cache far
  // better when the response is immutable. Replacing the film means shipping
  // a new filename, not overwriting this one.
  async headers() {
    return [
      {
        source: "/media/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },

  async redirects() {
    return [
      {
        source: "/recruiter",
        destination: "/recruiters",
        permanent: false,
      },
      {
        source: "/recruiter/:path*",
        destination: "/recruiters/workspace",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
