/**
 * /student/vbr (legacy Proof Studio index) — dashboard consolidation Stage 2.
 *
 * The old Proof Studio home now forwards to the canonical Student Dashboard's
 * Proofs section. Only the exact index redirects — /student/vbr/** sub-routes
 * (recorder sessions, passport, vault, project reports) are separate route
 * files this page never intercepts. The behavior the old page protected
 * (defense projects are never advertised as recordable walkthroughs) is now
 * covered by student-dashboard.test.tsx.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"

const redirectMock = vi.fn((path: string) => {
  // Mirror Next.js semantics: redirect() never returns.
  throw new Error(`NEXT_REDIRECT:${path}`)
})

vi.mock("next/navigation", () => ({
  redirect: (path: string) => redirectMock(path),
}))

import LegacyProofStudioPage from "../app/student/vbr/page"

beforeEach(() => {
  redirectMock.mockClear()
})

describe("/student/vbr legacy index", () => {
  it("redirects to the canonical dashboard's Proofs section", () => {
    expect(() => LegacyProofStudioPage()).toThrow("NEXT_REDIRECT:/student?section=proofs")
    expect(redirectMock).toHaveBeenCalledTimes(1)
    expect(redirectMock).toHaveBeenCalledWith("/student?section=proofs")
  })
})
