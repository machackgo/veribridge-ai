/**
 * Passport Profile editor — frontend tests.
 *
 * Covers: load + prefill suggestions, PATCH-style save of only changed
 * fields, field-error display, visibility toggles, live public preview, and
 * the guardrail that prefill hints are never auto-saved.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { PassportProfileEditor } from "../app/student/vbr/passport/profile/PassportProfileEditor"
import type { PassportProfileResponse } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getPassportProfile: vi.fn(),
  updatePassportProfile: vi.fn(),
  getWorkPassportStatus: vi.fn(),
  uploadPassportPhoto: vi.fn(),
  removePassportPhoto: vi.fn(),
}))

import {
  getPassportProfile,
  getWorkPassportStatus,
  updatePassportProfile,
} from "@/lib/vbr-api"

function makeResponse(overrides: Partial<PassportProfileResponse> = {}): PassportProfileResponse {
  return {
    profile: {
      full_name: null,
      preferred_name: null,
      pronunciation: null,
      headline: null,
      bio: null,
      institution: null,
      degree: null,
      graduation_year: null,
      location: null,
      github_url: null,
      linkedin_url: null,
      portfolio_url: null,
      role_areas: [],
      availability: null,
      work_authorization_note: null,
      show_location: true,
      show_availability: true,
      show_links: true,
      show_work_authorization: false,
      updated_at: null,
    },
    has_profile: false,
    avatar_url: null,
    prefill: {},
    ...overrides,
  }
}

beforeEach(() => {
  vi.mocked(getPassportProfile).mockReset()
  vi.mocked(updatePassportProfile).mockReset()
  vi.mocked(getWorkPassportStatus).mockReset()
  vi.mocked(getWorkPassportStatus).mockResolvedValue({
    is_published: true,
    public_slug: "slug123",
    public_path: "/p/slug123",
    published_at: "2026-01-01T00:00:00Z",
    headline: "Verified Work Passport",
    summary: "",
  } as never)
})

describe("PassportProfileEditor", () => {
  it("loads the stored profile into the form and preview", async () => {
    vi.mocked(getPassportProfile).mockResolvedValue(
      makeResponse({
        has_profile: true,
        profile: {
          ...makeResponse().profile,
          full_name: "Ada Lovelace",
          headline: "AI Engineer",
          institution: "WPI",
        },
      }),
    )

    render(<PassportProfileEditor />)

    expect(await screen.findByTestId("passport-profile-editor")).toBeInTheDocument()
    expect(screen.getByTestId("profile-full-name")).toHaveValue("Ada Lovelace")
    expect(screen.getByTestId("profile-preview")).toHaveTextContent("Ada Lovelace")
    expect(screen.getByTestId("profile-preview")).toHaveTextContent("AI Engineer")
  })

  it("saves only the changed fields (PATCH semantics)", async () => {
    vi.mocked(getPassportProfile).mockResolvedValue(
      makeResponse({
        has_profile: true,
        profile: { ...makeResponse().profile, full_name: "Ada Lovelace" },
      }),
    )
    vi.mocked(updatePassportProfile).mockResolvedValue(
      makeResponse({
        has_profile: true,
        profile: { ...makeResponse().profile, full_name: "Ada Lovelace", headline: "AI Engineer" },
      }),
    )

    render(<PassportProfileEditor />)
    await screen.findByTestId("passport-profile-editor")

    fireEvent.change(screen.getByTestId("profile-headline"), { target: { value: "AI Engineer" } })
    fireEvent.click(screen.getByTestId("profile-save"))

    await waitFor(() => expect(updatePassportProfile).toHaveBeenCalledTimes(1))
    // Only the changed field is sent — never the untouched ones.
    expect(vi.mocked(updatePassportProfile).mock.calls[0][0]).toEqual({ headline: "AI Engineer" })
    expect(await screen.findByTestId("profile-save-message")).toBeInTheDocument()
  })

  it("shows a field-level error from a validation failure and keeps editing enabled", async () => {
    vi.mocked(getPassportProfile).mockResolvedValue(makeResponse())
    vi.mocked(updatePassportProfile).mockRejectedValue(new Error("Link must be on github.com."))

    render(<PassportProfileEditor />)
    await screen.findByTestId("passport-profile-editor")

    fireEvent.change(screen.getByTestId("profile-github"), {
      target: { value: "https://gitlab.com/ada" },
    })
    fireEvent.click(screen.getByTestId("profile-save"))

    await waitFor(() => expect(updatePassportProfile).toHaveBeenCalled())
    expect(await screen.findByText("Link must be on github.com.")).toBeInTheDocument()
    // The save button remains usable for a retry.
    expect(screen.getByTestId("profile-save")).toBeEnabled()
  })

  it("offers prefill suggestions but never auto-saves them", async () => {
    vi.mocked(getPassportProfile).mockResolvedValue(
      makeResponse({ prefill: { full_name: "Ada Lovelace", institution: "WPI" } }),
    )

    render(<PassportProfileEditor />)
    await screen.findByTestId("passport-profile-editor")

    // Suggestion visible; form still empty; nothing saved on load.
    expect(screen.getByText("Use “Ada Lovelace”")).toBeInTheDocument()
    expect(screen.getByTestId("profile-full-name")).toHaveValue("")
    expect(updatePassportProfile).not.toHaveBeenCalled()

    // Accepting fills the form (still requires an explicit save).
    fireEvent.click(screen.getByText("Use “Ada Lovelace”"))
    expect(screen.getByTestId("profile-full-name")).toHaveValue("Ada Lovelace")
    expect(updatePassportProfile).not.toHaveBeenCalled()
  })

  it("renders visibility toggles with work authorization OFF by default", async () => {
    vi.mocked(getPassportProfile).mockResolvedValue(makeResponse())

    render(<PassportProfileEditor />)
    await screen.findByTestId("passport-profile-editor")

    expect(screen.getByTestId("toggle-show-location")).toBeChecked()
    expect(screen.getByTestId("toggle-show-links")).toBeChecked()
    expect(screen.getByTestId("toggle-show-availability")).toBeChecked()
    expect(screen.getByTestId("toggle-show-work-auth")).not.toBeChecked()
  })

  it("preview hides links when show_links is off", async () => {
    vi.mocked(getPassportProfile).mockResolvedValue(
      makeResponse({
        profile: {
          ...makeResponse().profile,
          full_name: "Ada Lovelace",
          github_url: "https://github.com/ada",
          show_links: false,
        },
        has_profile: true,
      }),
    )

    render(<PassportProfileEditor />)
    await screen.findByTestId("passport-profile-editor")

    expect(screen.getByTestId("profile-preview")).not.toHaveTextContent("GitHub")
  })
})
