import type { MetadataRoute } from "next"

// Served at /robots.txt (the auth proxy allowlists the path). Public,
// shareable surfaces are crawlable; authenticated app surfaces are not.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/privacy", "/extension", "/recruiters"],
        disallow: ["/dashboard", "/student", "/auth", "/login", "/api"],
      },
    ],
  }
}
