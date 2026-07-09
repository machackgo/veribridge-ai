/**
 * Beam short link (`/b/{code}`, Phase 2) — resolver + scan-target page tests.
 *
 * The backend resolver (`GET /api/v1/public/beam/{code}`) is the ONLY authority
 * on where a scanned code goes; this suite pins the frontend half of that
 * contract:
 *  - {@link resolveBeamCode} follows ONLY a clean active `/p/{slug}` answer —
 *    malformed codes never even hit the network, absolute URLs / private routes
 *    in a (hypothetically compromised) payload fail closed, backend 404/410 is
 *    `inactive`, and network/5xx is the retryable `unavailable`;
 *  - the `/b/[code]` server page issues a real redirect for an active code and
 *    otherwise renders the safe anonymous notice: exact required microcopy, a
 *    distinct retryable message for outages, and NO holder name / slug / code /
 *    reason detail anywhere in the output;
 *  - {@link beamShortUrl} builds production URLs from the configured app origin
 *    — never a hardcoded localhost.
 */

import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

import BeamShortLinkPage from "../app/b/[code]/page"
import { resolveBeamCode, BEAM_CODE_PATTERN } from "@/lib/beam-link"
import { beamShortUrl } from "@/lib/app-url"

const CODE = "k7GhQ2mZ9pTw4Rx_"

function fetchResponding(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

// ── resolveBeamCode ──────────────────────────────────────────────────────────

describe("resolveBeamCode", () => {
  it("returns the live public Passport path for an active code", async () => {
    vi.stubGlobal("fetch", fetchResponding(200, { status: "active", public_passport_path: "/p/slug123" }))
    await expect(resolveBeamCode(CODE)).resolves.toEqual({
      kind: "active",
      publicPassportPath: "/p/slug123",
    })
  })

  it("treats a malformed code as inactive WITHOUT calling the network", async () => {
    const fetchSpy = fetchResponding(200, {})
    vi.stubGlobal("fetch", fetchSpy)
    for (const bad of ["", "short", "has spaces in it", "semi;colon00000", "a".repeat(80)]) {
      await expect(resolveBeamCode(bad)).resolves.toEqual({ kind: "inactive" })
    }
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it("fails closed when a 200 payload names anything but a /p/{slug} path", async () => {
    for (const path of [
      "https://evil.example.com/p/slug123", // absolute URL — potential open redirect
      "/student/vbr/passport",              // private route
      "/p/slug123?x=1",                     // decorated path
      "//evil.example.com/p/s",             // protocol-relative
      "",
    ]) {
      vi.stubGlobal("fetch", fetchResponding(200, { status: "active", public_passport_path: path }))
      await expect(resolveBeamCode(CODE)).resolves.toEqual({ kind: "inactive" })
    }
  })

  it("maps backend 404/410 to inactive and 5xx / network failure to unavailable", async () => {
    vi.stubGlobal("fetch", fetchResponding(404, { detail: { code: "beam_link_inactive" } }))
    await expect(resolveBeamCode(CODE)).resolves.toEqual({ kind: "inactive" })

    vi.stubGlobal("fetch", fetchResponding(500, {}))
    await expect(resolveBeamCode(CODE)).resolves.toEqual({ kind: "unavailable" })

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")))
    await expect(resolveBeamCode(CODE)).resolves.toEqual({ kind: "unavailable" })
  })

  it("accepts exactly the minted code shape", () => {
    expect(BEAM_CODE_PATTERN.test("abcDEF123456-_XX")).toBe(true)
    expect(BEAM_CODE_PATTERN.test("abcDEF12345")).toBe(false) // 11 chars — too short
    expect(BEAM_CODE_PATTERN.test("abcDEF123456!!")).toBe(false)
  })
})

// ── /b/[code] scan-target page ───────────────────────────────────────────────

async function renderPage(code: string) {
  const jsx = await BeamShortLinkPage({ params: Promise.resolve({ code }) })
  render(jsx)
}

describe("/b/[code] page", () => {
  it("redirects to the live public Passport for an active code", async () => {
    vi.stubGlobal("fetch", fetchResponding(200, { status: "active", public_passport_path: "/p/slug123" }))
    // next/navigation's redirect() aborts rendering by throwing NEXT_REDIRECT.
    await expect(
      BeamShortLinkPage({ params: Promise.resolve({ code: CODE }) }),
    ).rejects.toMatchObject({ digest: expect.stringContaining("NEXT_REDIRECT") })
  })

  it("renders the safe inactive notice for a dead code — required microcopy, zero holder data", async () => {
    vi.stubGlobal("fetch", fetchResponding(404, { detail: { code: "beam_link_inactive" } }))
    await renderPage(CODE)
    expect(screen.getByTestId("beam-link-inactive")).toHaveTextContent(
      "This Passport link is no longer active",
    )
    expect(screen.getByTestId("beam-link-notice")).toHaveTextContent(
      "Ask for an updated link from the holder.",
    )
    expect(screen.getByTestId("beam-link-learn-more")).toHaveTextContent("Learn about VeriBridge")

    const text = document.body.textContent ?? ""
    expect(text).not.toContain(CODE)          // never echo the scanned code
    expect(text).not.toContain("slug123")     // never a slug
    expect(text).not.toMatch(/revoked|expired|unpublished/i) // no reason detail
    expect(text).not.toMatch(/Jordan|Rivera/) // no holder identity, ever
  })

  it("renders the distinct retryable notice when the resolver is unreachable — never 'no longer active'", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("api down")))
    await renderPage(CODE)
    expect(screen.getByTestId("beam-link-unavailable")).toHaveTextContent(
      /couldn’t check this link right now/i,
    )
    expect(screen.queryByTestId("beam-link-inactive")).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/no longer active/i)
  })

  it("shows the inactive notice for junk codes without any network call", async () => {
    const fetchSpy = fetchResponding(200, {})
    vi.stubGlobal("fetch", fetchSpy)
    await renderPage("../../etc/passwd")
    expect(screen.getByTestId("beam-link-inactive")).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

// ── Short URL generation ─────────────────────────────────────────────────────

describe("beamShortUrl", () => {
  it("uses the configured production origin — no hardcoded localhost", () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com")
    expect(beamShortUrl(CODE)).toBe(`https://veribridgeai.com/b/${CODE}`)
    expect(beamShortUrl(CODE)).not.toContain("localhost")
  })

  it("falls back to the browser origin in local dev", () => {
    expect(beamShortUrl(CODE)).toBe(`${window.location.origin}/b/${CODE}`)
  })
})
