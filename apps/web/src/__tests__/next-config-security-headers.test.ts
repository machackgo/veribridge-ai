import { describe, expect, it } from "vitest"

import nextConfig, { SECURITY_HEADERS } from "../../next.config"

describe("next.config security headers", () => {
  it("applies the baseline security headers to every route", async () => {
    const rules = (await nextConfig.headers?.()) ?? []
    const all = rules.find((rule) => rule.source === "/:path*")
    expect(all).toBeDefined()
    const byKey = Object.fromEntries(all!.headers.map((h) => [h.key, h.value]))
    expect(byKey["X-Content-Type-Options"]).toBe("nosniff")
    expect(byKey["Referrer-Policy"]).toBe("strict-origin-when-cross-origin")
    expect(byKey["X-Frame-Options"]).toBe("DENY")
    expect(byKey["Strict-Transport-Security"]).toBe("max-age=63072000; includeSubDomains")
    expect(byKey["Permissions-Policy"]).toContain("camera=(self)")
    expect(byKey["Permissions-Policy"]).toContain("microphone=(self)")
    expect(byKey["Permissions-Policy"]).toContain("display-capture=(self)")
  })

  it("sets only frame-ancestors via CSP (no full policy that could break the app)", () => {
    const csp = SECURITY_HEADERS.filter((h) => h.key === "Content-Security-Policy")
    expect(csp).toHaveLength(1)
    expect(csp[0].value).toBe("frame-ancestors 'none'")
  })

  it("keeps the immutable cache rule for launch-film media", async () => {
    const rules = (await nextConfig.headers?.()) ?? []
    const media = rules.find((rule) => rule.source === "/media/:path*")
    expect(media?.headers).toContainEqual({
      key: "Cache-Control",
      value: "public, max-age=31536000, immutable",
    })
  })
})
