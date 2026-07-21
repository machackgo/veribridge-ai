/**
 * Security-focused tests for the recruiter report link/token parser.
 *
 * The parser is the single gate for everything a recruiter pastes or scans:
 * it may only ever yield an internally constructed same-app path, so these
 * tests double as the open-redirect / scheme-abuse regression suite.
 */

import { afterEach, describe, expect, it, vi } from "vitest"

import { parseReportLink, REPORT_LINK_REJECTION_MESSAGES, trustedReportOrigins } from "@/lib/report-link"

const TOKEN = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345" // 32 chars, backend shape
const APP = "http://localhost:3000" // vitest jsdom origin

afterEach(() => {
  vi.unstubAllEnvs()
})

describe("parseReportLink — accepted shapes", () => {
  it("accepts a raw public token and builds the canonical internal path", () => {
    const parse = parseReportLink(TOKEN)
    expect(parse).toEqual({
      ok: true,
      token: TOKEN,
      path: `/vbr/report/${TOKEN}`,
      kind: "token",
      legacy: false,
    })
  })

  it("trims surrounding whitespace before parsing", () => {
    const parse = parseReportLink(`   ${TOKEN}\n`)
    expect(parse.ok).toBe(true)
  })

  it("accepts a canonical report URL on the app origin", () => {
    const parse = parseReportLink(`${APP}/vbr/report/${TOKEN}`)
    expect(parse).toMatchObject({ ok: true, token: TOKEN, path: `/vbr/report/${TOKEN}`, kind: "url" })
  })

  it("accepts a legacy /r/ report URL and keeps it on the legacy route", () => {
    const parse = parseReportLink(`${APP}/r/${TOKEN}`)
    expect(parse).toMatchObject({ ok: true, token: TOKEN, path: `/r/${TOKEN}`, legacy: true })
  })

  it("accepts mixed-case scheme/host (URL normalization)", () => {
    const parse = parseReportLink(`HTTP://LOCALHOST:3000/vbr/report/${TOKEN}`)
    expect(parse).toMatchObject({ ok: true, token: TOKEN })
  })

  it("accepts the configured NEXT_PUBLIC_APP_URL origin, including schemeless paste", () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "https://veribridgeai.com")
    expect(parseReportLink(`https://veribridgeai.com/vbr/report/${TOKEN}`).ok).toBe(true)
    expect(parseReportLink(`veribridgeai.com/vbr/report/${TOKEN}`).ok).toBe(true)
  })

  it("discards query strings and fragments — the destination is rebuilt from the token", () => {
    const parse = parseReportLink(
      `${APP}/vbr/report/${TOKEN}?next=https://evil.example.com#//evil`,
    )
    expect(parse).toMatchObject({ ok: true, path: `/vbr/report/${TOKEN}` })
  })
})

describe("parseReportLink — rejections", () => {
  it("rejects empty and whitespace-only input", () => {
    expect(parseReportLink("")).toEqual({ ok: false, reason: "empty" })
    expect(parseReportLink("   ")).toEqual({ ok: false, reason: "empty" })
  })

  it("rejects oversized input outright", () => {
    expect(parseReportLink(`${APP}/vbr/report/${"a".repeat(5000)}`)).toEqual({
      ok: false,
      reason: "too_long",
    })
  })

  it("rejects tokens outside the minted shape", () => {
    expect(parseReportLink("shortTok").ok).toBe(false)
    expect(parseReportLink("a".repeat(65)).ok).toBe(false)
    expect(parseReportLink("has spaces in it definitely").ok).toBe(false)
    expect(parseReportLink("token!with@symbols#12345").ok).toBe(false)
  })

  it("rejects javascript: and data: schemes", () => {
    expect(parseReportLink("javascript:alert(document.cookie)")).toEqual({
      ok: false,
      reason: "unsupported_scheme",
    })
    expect(parseReportLink(`data:text/html,<script>1</script>`)).toEqual({
      ok: false,
      reason: "unsupported_scheme",
    })
  })

  it("rejects protocol-relative URLs", () => {
    expect(parseReportLink(`//evil.example.com/vbr/report/${TOKEN}`)).toEqual({
      ok: false,
      reason: "unsupported_scheme",
    })
  })

  it("rejects report-shaped URLs on attacker origins", () => {
    for (const url of [
      `https://evil.example.com/vbr/report/${TOKEN}`,
      `https://veribridgeai.com.evil.example.com/vbr/report/${TOKEN}`,
      `http://localhost:9999/vbr/report/${TOKEN}`,
    ]) {
      expect(parseReportLink(url)).toEqual({ ok: false, reason: "foreign_origin" })
    }
  })

  it("rejects same-origin URLs that are not report routes", () => {
    expect(parseReportLink(`${APP}/p/some-passport`)).toEqual({
      ok: false,
      reason: "not_a_report_link",
    })
    expect(parseReportLink(`${APP}/vbr/report/${TOKEN}/extra`)).toEqual({
      ok: false,
      reason: "not_a_report_link",
    })
    expect(parseReportLink(`${APP}/`)).toEqual({ ok: false, reason: "not_a_report_link" })
  })

  it("rejects encoded traversal and malformed percent-encoding in the token segment", () => {
    expect(parseReportLink(`${APP}/vbr/report/%2e%2e%2fadmin`).ok).toBe(false)
    expect(parseReportLink(`${APP}/vbr/report/%zzbroken`).ok).toBe(false)
    // Encoded slash may not smuggle extra segments into a "token".
    expect(parseReportLink(`${APP}/vbr/report/abc%2Fdef%2Fghi%2Fjkl`).ok).toBe(false)
  })

  it("rejects an encoded redirect payload masquerading as a token", () => {
    const encoded = encodeURIComponent("https://evil.example.com/steal")
    expect(parseReportLink(`${APP}/vbr/report/${encoded}`).ok).toBe(false)
  })

  it("has a human-readable message for every rejection reason", () => {
    for (const message of Object.values(REPORT_LINK_REJECTION_MESSAGES)) {
      expect(message.length).toBeGreaterThan(10)
    }
  })
})

describe("trustedReportOrigins", () => {
  it("includes the browser origin and deduplicates the configured app URL", () => {
    vi.stubEnv("NEXT_PUBLIC_APP_URL", "http://localhost:3000/")
    expect(trustedReportOrigins()).toEqual(["http://localhost:3000"])
  })
})
