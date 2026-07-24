/**
 * Privacy & Sharing center (`/student/vbr/passport/privacy`) — rendering and
 * interaction tests against a mocked DisclosureContext.
 *
 * Covers: the three access-mode cards, the honest effective-exposure summary
 * (zeros render as "0"), per-project aspect controls staging into the
 * unsaved-changes bar and publishing as ONE batch PUT, "Use default"
 * (visibility null), the document view/download split, skill/claim hierarchy
 * microcopy, the recruiter-safe locked state, and the Private-mode banner via
 * the confirmation dialog.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { PrivacyCenterView } from "../app/student/vbr/passport/privacy/PrivacyCenterView"
import type { DisclosureContext } from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  getDisclosureContext: vi.fn(),
  setDisclosureMode: vi.fn(),
  applyDisclosureOverrides: vi.fn(),
  applyDisclosurePreset: vi.fn(),
  resetDisclosure: vi.fn(),
  publishWorkPassport: vi.fn(),
  unpublishWorkPassport: vi.fn(),
}))

import {
  applyDisclosureOverrides,
  applyDisclosurePreset,
  getDisclosureContext,
  resetDisclosure,
  setDisclosureMode,
  unpublishWorkPassport,
} from "@/lib/vbr-api"

function makeContext(overrides: Partial<DisclosureContext> = {}): DisclosureContext {
  return {
    passport: {
      is_published: true,
      public_slug: "abc123",
      public_path: "/p/abc123",
      preview_public_path: "/p/abc123",
      mode: "custom",
      disclosure_version: 3,
      custom_overrides_active: true,
      override_count: 2,
    },
    projects: [
      {
        project_id: "proj-1",
        title: "Skill Evidence Tracker",
        public_report_path: "/vbr/report/tok-1",
        published_at: "2026-07-01T00:00:00Z",
        project: { configured: null, effective: "visible", allowed: ["visible", "hidden"] },
        report: { configured: null, effective: "visible", allowed: ["visible", "hidden"] },
        aspects: [
          {
            resource_type: "github_repo",
            resource_key: "proj-1",
            label: "GitHub repository access",
            description: "Whether recruiters can open the repository behind this project.",
            available: true,
            configured: "viewable",
            effective: "viewable",
            default: "summary",
            allowed: ["hidden", "summary", "viewable"],
          },
          {
            resource_type: "github_lines",
            resource_key: "proj-1",
            label: "Exact code references",
            description: "Line-level code evidence references.",
            available: true,
            configured: null,
            effective: "hidden",
            default: "hidden",
            allowed: ["hidden", "viewable"],
          },
          {
            resource_type: "website_summary",
            resource_key: "proj-1",
            label: "Website behaviour summary",
            description: "The verified summary of the recorded website workflow.",
            available: false,
            configured: null,
            effective: "hidden",
            default: "visible",
            allowed: ["visible", "hidden"],
          },
          {
            resource_type: "defense_summary",
            resource_key: "proj-1",
            label: "Defense summary",
            description: "The qualitative Project Defense assessment.",
            available: true,
            configured: null,
            effective: "visible",
            default: "visible",
            allowed: ["visible", "hidden"],
          },
        ],
        documents: [
          {
            document_key: "doc-1",
            title: "Final report",
            source_type: "document",
            configured: "viewable",
            effective: "viewable",
            default: "summary",
            allowed: ["hidden", "summary", "viewable"],
            download_configured: null,
            effective_downloadable: false,
            has_retained_original: true,
          },
          {
            document_key: "doc-2",
            title: "Design doc",
            source_type: "document",
            configured: null,
            effective: "summary",
            default: "summary",
            allowed: ["hidden", "summary", "viewable"],
            download_configured: null,
            effective_downloadable: false,
            has_retained_original: false,
          },
        ],
        override_count: 2,
      },
    ],
    skill_groups: [
      {
        category: "Programming Languages",
        configured: "hidden",
        effective: "hidden",
        allowed: ["visible", "hidden"],
        skills: [
          {
            skill: "Python",
            skill_slug: "python",
            category: "Programming Languages",
            configured: "visible",
            effective: "hidden",
            allowed: ["visible", "hidden"],
            effectively_public: false,
            project_claims: [
              {
                project_id: "proj-1",
                project_title: "Skill Evidence Tracker",
                resource_key: "proj-1:python",
                configured: null,
                effective: "hidden",
                allowed: ["visible", "hidden"],
              },
            ],
          },
        ],
      },
    ],
    summary: {
      projects_public: 1,
      skills_public: 4,
      skill_groups_public: 2,
      github_repositories_viewable: 1,
      exact_code_references: 0,
      websites_public: 0,
      website_screenshot_sets: 0,
      website_recordings_viewable: 0,
      document_summaries: 1,
      documents_viewable: 1,
      document_downloads: 0,
      defense_summaries: 1,
      defense_transcripts_viewable: 0,
      defense_recordings_viewable: 0,
      video_moments_public: 0,
    },
    ...overrides,
  }
}

async function renderCenter(context = makeContext()) {
  vi.mocked(getDisclosureContext).mockResolvedValue(context)
  render(<PrivacyCenterView />)
  await screen.findByTestId("privacy-center")
}

function expandFirstProject() {
  fireEvent.click(screen.getAllByTestId("privacy-project-card-toggle")[0])
}

beforeEach(() => {
  vi.mocked(getDisclosureContext).mockReset()
  vi.mocked(setDisclosureMode).mockReset()
  vi.mocked(applyDisclosureOverrides).mockReset()
  vi.mocked(applyDisclosurePreset).mockReset()
  vi.mocked(resetDisclosure).mockReset()
  vi.mocked(unpublishWorkPassport).mockReset()
})

describe("PrivacyCenterView — modes and summary", () => {
  it("renders the three access modes with the current one selected", async () => {
    await renderCenter()

    expect(screen.getByTestId("privacy-mode-private")).toHaveAttribute("aria-pressed", "false")
    expect(screen.getByTestId("privacy-mode-recruiter_safe")).toHaveAttribute("aria-pressed", "false")
    expect(screen.getByTestId("privacy-mode-custom")).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByText("Recommended")).toBeInTheDocument()
    // Preview opens the public path in a new tab.
    const preview = screen.getByTestId("privacy-preview-link")
    expect(preview).toHaveAttribute("href", "/p/abc123")
    expect(preview).toHaveAttribute("target", "_blank")
  })

  it("renders the effective exposure summary including honest zero rows", async () => {
    await renderCenter()

    const summary = screen.getByTestId("privacy-summary")
    const row = (key: string) => summary.querySelector(`[data-summary-key="${key}"]`)
    expect(row("projects_public")?.textContent).toContain("1")
    expect(row("github_repositories_viewable")?.textContent).toContain("GitHub repositories viewable")
    // Zeros are rendered as "0", never omitted — that is the trust contract.
    expect(row("document_downloads")?.textContent).toContain("0")
    expect(row("document_downloads")?.textContent).toContain("document downloads")
    expect(row("exact_code_references")?.textContent).toContain("0")
  })

  it("renders one collapsible card per project with the effective one-liner and override badge", async () => {
    await renderCenter()

    const card = screen.getAllByTestId("privacy-project-card")[0]
    expect(card).toHaveTextContent("Skill Evidence Tracker")
    expect(card).toHaveTextContent("Report: Public")
    expect(card).toHaveTextContent("GitHub: Viewable")
    expect(card).toHaveTextContent("Documents: 1 viewable, 1 summary")
    expect(card).toHaveTextContent("Defense: Public")
    expect(card).toHaveTextContent("2 custom")
    // Collapsed by default — aspect rows appear only after expanding.
    expect(screen.queryByTestId("privacy-aspect-github_repo")).not.toBeInTheDocument()
    expandFirstProject()
    expect(screen.getByTestId("privacy-aspect-github_repo")).toBeInTheDocument()
  })

  it("dims unavailable aspects with 'Not attached' and disables their controls", async () => {
    await renderCenter()
    expandFirstProject()

    const row = screen.getByTestId("privacy-aspect-website_summary")
    expect(row).toHaveTextContent("Not attached")
    for (const btn of Array.from(row.querySelectorAll("button"))) {
      expect(btn).toBeDisabled()
    }
  })
})

describe("PrivacyCenterView — staging and batch publish", () => {
  it("stages an aspect change, reviews it, and publishes ONE overrides batch", async () => {
    await renderCenter()
    expandFirstProject()

    const row = screen.getByTestId("privacy-aspect-github_repo")
    // Currently "viewable" (custom); narrow to summary-only.
    fireEvent.click(within(row).getByRole("button", { name: "Summary" }))

    const bar = screen.getByTestId("privacy-unsaved-bar")
    expect(bar).toHaveTextContent("1 unsaved change")

    fireEvent.click(screen.getByTestId("privacy-save"))
    const dialog = screen.getByTestId("privacy-confirm-dialog")
    expect(dialog).toHaveAttribute("aria-modal", "true")
    // The review dialog lists the change as old → new.
    expect(screen.getByTestId("privacy-review-list")).toHaveTextContent("GitHub repository access")
    expect(screen.getByTestId("privacy-review-list")).toHaveTextContent("Viewable → Summary")

    vi.mocked(applyDisclosureOverrides).mockResolvedValue(makeContext())
    fireEvent.click(screen.getByTestId("privacy-confirm-submit"))

    await waitFor(() =>
      expect(applyDisclosureOverrides).toHaveBeenCalledWith([
        { resource_type: "github_repo", resource_key: "proj-1", visibility: "summary" },
      ]),
    )
    // Success status announced; the unsaved bar is gone.
    expect(await screen.findByTestId("privacy-status")).toHaveTextContent("1 privacy change")
    expect(screen.getByTestId("privacy-status")).toHaveAttribute("role", "status")
    expect(screen.queryByTestId("privacy-unsaved-bar")).not.toBeInTheDocument()
  })

  it("'Use default' stages a null visibility that clears the override", async () => {
    await renderCenter()
    expandFirstProject()

    fireEvent.click(screen.getByTestId("privacy-aspect-github_repo-use-default"))
    expect(screen.getByTestId("privacy-unsaved-bar")).toHaveTextContent("1 unsaved change")

    fireEvent.click(screen.getByTestId("privacy-save"))
    vi.mocked(applyDisclosureOverrides).mockResolvedValue(makeContext())
    fireEvent.click(screen.getByTestId("privacy-confirm-submit"))

    await waitFor(() =>
      expect(applyDisclosureOverrides).toHaveBeenCalledWith([
        { resource_type: "github_repo", resource_key: "proj-1", visibility: null },
      ]),
    )
  })

  it("discards staged changes without any server call", async () => {
    await renderCenter()
    expandFirstProject()

    const row = screen.getByTestId("privacy-aspect-github_repo")
    fireEvent.click(within(row).getByRole("button", { name: "Hidden" }))
    expect(screen.getByTestId("privacy-unsaved-bar")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("privacy-discard"))
    expect(screen.queryByTestId("privacy-unsaved-bar")).not.toBeInTheDocument()
    expect(applyDisclosureOverrides).not.toHaveBeenCalled()
  })

  it("cancelling the review dialog never publishes", async () => {
    await renderCenter()
    expandFirstProject()

    const row = screen.getByTestId("privacy-aspect-github_repo")
    fireEvent.click(within(row).getByRole("button", { name: "Hidden" }))
    fireEvent.click(screen.getByTestId("privacy-save"))
    fireEvent.click(screen.getByTestId("privacy-confirm-cancel"))

    expect(screen.queryByTestId("privacy-confirm-dialog")).not.toBeInTheDocument()
    expect(applyDisclosureOverrides).not.toHaveBeenCalled()
    // The staged change is still pending after cancel.
    expect(screen.getByTestId("privacy-unsaved-bar")).toBeInTheDocument()
  })
})

describe("PrivacyCenterView — documents", () => {
  it("splits document visibility from download permission (view-only vs downloadable)", async () => {
    await renderCenter()
    expandFirstProject()

    const rows = screen.getAllByTestId("privacy-doc-row")
    const viewableDoc = rows.find((r) => r.getAttribute("data-document-key") === "doc-1")!
    const summaryDoc = rows.find((r) => r.getAttribute("data-document-key") === "doc-2")!

    // Viewable doc: download toggle enabled, currently view-only.
    const viewableToggle = within(viewableDoc).getByTestId("privacy-doc-download-toggle")
    expect(viewableToggle).toBeEnabled()
    expect(viewableToggle).toHaveAttribute("aria-pressed", "false")
    expect(viewableDoc).toHaveTextContent("View only")

    // Summary doc: downloads impossible until the doc itself is viewable.
    expect(within(summaryDoc).getByTestId("privacy-doc-download-toggle")).toBeDisabled()

    // Enabling download stages a document_download change keyed by the doc.
    fireEvent.click(viewableToggle)
    expect(viewableToggle).toHaveAttribute("aria-pressed", "true")
    fireEvent.click(screen.getByTestId("privacy-save"))
    vi.mocked(applyDisclosureOverrides).mockResolvedValue(makeContext())
    fireEvent.click(screen.getByTestId("privacy-confirm-submit"))
    await waitFor(() =>
      expect(applyDisclosureOverrides).toHaveBeenCalledWith([
        { resource_type: "document_download", resource_key: "doc-1", visibility: "downloadable" },
      ]),
    )
  })

  it("shows the honest not-retained note when a viewable doc has no original file", async () => {
    await renderCenter()
    expandFirstProject()

    const summaryDoc = screen
      .getAllByTestId("privacy-doc-row")
      .find((r) => r.getAttribute("data-document-key") === "doc-2")!
    expect(summaryDoc).not.toHaveTextContent("Original file not retained")
    // Stage doc-2 to viewable — the honest note appears immediately.
    fireEvent.click(within(summaryDoc).getByRole("button", { name: "Viewable" }))
    expect(summaryDoc).toHaveTextContent("Original file not retained — summary shown.")
  })
})

describe("PrivacyCenterView — skills hierarchy", () => {
  it("renders group, skill, and per-project claim rows with hidden-because microcopy", async () => {
    await renderCenter()

    const group = screen.getAllByTestId("privacy-skill-group")[0]
    expect(group).toHaveTextContent("Programming Languages")
    fireEvent.click(within(group).getByTestId("privacy-skill-group-toggle"))

    const skillRow = screen.getByTestId("privacy-skill-row")
    expect(skillRow).toHaveTextContent("Python")
    // Configured visible but the group is hidden → honest effective microcopy.
    expect(skillRow).toHaveTextContent("Effective: Hidden because the skill group is hidden.")

    const claimRow = screen.getByTestId("privacy-claim-row")
    expect(claimRow).toHaveTextContent("in Skill Evidence Tracker")
  })
})

describe("PrivacyCenterView — recruiter-safe and private modes", () => {
  it("locks individual controls in recruiter-safe mode with a switch-to-custom CTA", async () => {
    const ctx = makeContext()
    ctx.passport.mode = "recruiter_safe"
    await renderCenter(ctx)

    expect(screen.getByTestId("privacy-locked-note")).toHaveTextContent("Custom disclosure")
    expect(screen.getByTestId("privacy-switch-to-custom")).toBeInTheDocument()
    // No presets row outside custom mode.
    expect(screen.queryByTestId("privacy-preset-portfolio_open")).not.toBeInTheDocument()

    expandFirstProject()
    const row = screen.getByTestId("privacy-aspect-github_repo")
    for (const btn of Array.from(row.querySelectorAll("button"))) {
      expect(btn).toBeDisabled()
    }
  })

  it("switching to Private confirms first, then unpublishes and shows the kept-settings banner", async () => {
    const published = makeContext()
    const unpublished = makeContext()
    unpublished.passport = { ...unpublished.passport, is_published: false, public_path: null }
    vi.mocked(getDisclosureContext).mockResolvedValueOnce(published).mockResolvedValueOnce(unpublished)
    vi.mocked(unpublishWorkPassport).mockResolvedValue({
      is_published: false,
      public_slug: null,
      public_path: null,
      published_at: null,
      headline: "",
      summary: "",
    })

    render(<PrivacyCenterView />)
    await screen.findByTestId("privacy-center")

    fireEvent.click(screen.getByTestId("privacy-mode-private"))
    // Nothing happens before explicit confirmation.
    expect(unpublishWorkPassport).not.toHaveBeenCalled()
    expect(screen.getByTestId("privacy-confirm-dialog")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("privacy-confirm-submit"))
    await waitFor(() => expect(unpublishWorkPassport).toHaveBeenCalledTimes(1))
    expect(await screen.findByTestId("privacy-private-banner")).toHaveTextContent("settings below are kept")
    expect(screen.getByTestId("privacy-mode-private")).toHaveAttribute("aria-pressed", "true")
  })

  it("applying a preset requires confirmation and refreshes from the server response", async () => {
    await renderCenter()

    fireEvent.click(screen.getByTestId("privacy-preset-maximum_privacy"))
    expect(applyDisclosurePreset).not.toHaveBeenCalled()
    expect(screen.getByTestId("privacy-confirm-dialog")).toBeInTheDocument()

    vi.mocked(applyDisclosurePreset).mockResolvedValue(makeContext())
    fireEvent.click(screen.getByTestId("privacy-confirm-submit"))
    await waitFor(() => expect(applyDisclosurePreset).toHaveBeenCalledWith("maximum_privacy"))
    expect(await screen.findByTestId("privacy-status")).toHaveTextContent("Maximum privacy")
  })
})
