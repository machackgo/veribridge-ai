/**
 * Original Proof Access — rendering tests.
 *
 * Covers the trust layer that answers, for every proof in a Skill Report:
 * can the recruiter independently inspect the ORIGINAL evidence source, how,
 * and — when they cannot — why not:
 *
 *   • the report-level "Recruiter verification access" summary (derived only
 *     from actual availability),
 *   • the per-chain "Original proof access" strip (live URL vs recorded
 *     frames vs excerpts-only vs transcript, each with honest copy),
 *   • the owner-only captured-frames gallery (streamed through the authorized
 *     thumbnail proxy — no storage paths / signed URLs in the DOM),
 *   • the owner-only defense transcript viewer with cited-moment highlights,
 *   • fail-closed behaviour: public surfaces and missing artifacts never
 *     produce fake access buttons.
 */

import { render, screen, fireEvent, within } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"

import { SkillReportView } from "../../components/passport/VaultProofs"
import {
  deriveChainAccessRows,
  deriveVerificationAccessRows,
} from "../../components/passport/OriginalProofAccess"
import type {
  SkillReport,
  SkillReportProjectChain,
  WebsiteEvidenceCard,
} from "@/lib/vbr-api"

vi.mock("@/lib/vbr-api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/vbr-api")>()),
  listWebsiteProofFrames: vi.fn(),
  fetchFrameThumbnailObjectUrl: vi.fn(),
  getVBRSessionTranscript: vi.fn(),
}))

import {
  fetchFrameThumbnailObjectUrl,
  getVBRSessionTranscript,
  listWebsiteProofFrames,
} from "@/lib/vbr-api"

// ── Fixtures ──────────────────────────────────────────────────────────────────

function emptyStandalone(): SkillReport["standalone_evidence"] {
  return { github: [], website: [], documents: [], document_more_count: 0, defense: [], video: [], skill_graph: [] }
}

function skillReport(overrides: Partial<SkillReport> = {}): SkillReport {
  return {
    skill: "Machine Learning",
    skill_slug: "machine-learning",
    requested_skill: "machine-learning",
    category: "AI / Machine Learning",
    status: "Demonstrated",
    summary: "Proof sources support Machine Learning.",
    source_counts: {},
    overview: {
      skill: "Machine Learning",
      category: "AI / Machine Learning",
      status: "Demonstrated",
      proof_source_counts: {},
      proof_count: 1,
      attached_count: 1,
      unattached_count: 0,
      project_count: 1,
      why_supported: "Connected proof supports Machine Learning.",
      gaps: [],
    },
    projects: [],
    standalone_evidence: emptyStandalone(),
    github: [],
    website: [],
    documents: [],
    defense: [],
    video: [],
    skill_graph: [],
    gaps: [],
    generated_at: "2026-07-01T00:00:00Z",
    ...overrides,
  }
}

function chain(overrides: Partial<SkillReportProjectChain> = {}): SkillReportProjectChain {
  return {
    project_id: "proj-1",
    project_title: "Crash Risk Predictor",
    attached: true,
    attached_status: "Attached to project",
    sources: [],
    evidence_chain_summary: "Connected evidence chain.",
    github_evidence: [],
    website_evidence: [],
    document_correlations: [],
    document_more_count: 0,
    defense_evidence: [],
    video_evidence: [],
    limitations: [],
    ...overrides,
  }
}

function websiteCard(overrides: Partial<WebsiteEvidenceCard> = {}): WebsiteEvidenceCard {
  return {
    card_key: "web-abc",
    route_or_page: "demo.example.com/dashboard",
    website_purpose_key: "prediction_result_display",
    website_purpose_label: "Prediction / result display",
    website_purpose_summary: "The recorded page showed a prediction/result display.",
    skill_relevance_key: "ml_product_behavior_context",
    skill_relevance_label: "Machine Learning product behaviour context",
    skill_relevance_summary: "Product behaviour context — not implementation proof.",
    evidence_basis_chips: ["Route observed", "Visual frame"],
    limitation: "Runtime behaviour evidence; it does not, by itself, prove implementation.",
    screenshot_available: true,
    screenshot_access_label: "private_candidate_permission_required",
    verification_mode: "recorded_replay_only",
    verification_mode_label: "Recorded replay only",
    deployment_recommended: true,
    is_public_live_url: false,
    is_local_or_private_url: true,
    open_website_url: null,
    ...overrides,
  }
}

function websiteItem(
  card: WebsiteEvidenceCard | null,
  overrides: Record<string, unknown> = {},
): SkillReport["website"][number] {
  return {
    proof_type: "Website Proof",
    source_id: "sess-web-1",
    title: "Website Proof",
    safe_summary: "A recorded workflow was analyzed.",
    safe_location: "deployment",
    public_safe: false,
    is_attached_to_project: true,
    attached_project_ids: ["proj-1"],
    project_titles: ["Crash Risk Predictor"],
    limitation: "Runtime behaviour evidence only.",
    workflow_steps: [],
    public_url: null,
    website_evidence_card: card,
    ...overrides,
  } as SkillReport["website"][number]
}

function defenseGroupChain(overrides: Partial<SkillReportProjectChain> = {}): SkillReportProjectChain {
  return chain({
    sources: ["Project Defense"],
    defense_group: {
      explanation: "The candidate explained the training pipeline.",
      moments: [
        {
          label: "Training pipeline explanation",
          timestamp_label: "0:45",
          short_summary: "Explained feature engineering.",
          source_id: "sess-def-1",
        },
      ],
      grouped_count: 1,
      limitation: "Explanation evidence only.",
      source_ids: ["sess-def-1"],
    },
    ...overrides,
  })
}

const TRANSCRIPT = {
  session_id: "sess-def-1",
  status: "completed",
  transcript_id: "t-1",
  provider: "whisper",
  language: "en",
  segment_count: 2,
  duration_s: 90,
  preview_text: "",
  truncated: false,
  segments: [
    { start_s: 0, end_s: 30, text: "First I collected the accident dataset." },
    { start_s: 40, end_s: 60, text: "Then I engineered features and trained the model." },
  ],
}

beforeEach(() => {
  vi.mocked(listWebsiteProofFrames).mockReset()
  vi.mocked(fetchFrameThumbnailObjectUrl).mockReset()
  vi.mocked(getVBRSessionTranscript).mockReset()
})

// ── Recruiter verification access summary ─────────────────────────────────────

describe("Recruiter verification access summary", () => {
  it("renders one honest row per proof source actually present", () => {
    const report = skillReport({
      proof_chains: [
        chain({
          sources: ["GitHub Proof", "Website Proof", "Document Proof"],
          github_evidence: [
            {
              proof_type: "GitHub Proof",
              source_id: "gh-1",
              title: "octocat/predictor",
              safe_summary: "Implementation evidence.",
              public_safe: true,
              is_attached_to_project: true,
              attached_project_ids: ["proj-1"],
              project_titles: [],
              limitation: "",
              workflow_steps: [],
              github_line_url: "https://github.com/octocat/predictor/blob/main/train.py#L10-L42",
              public_url: "https://github.com/octocat/predictor",
            } as SkillReport["github"][number],
          ],
          website_evidence: [websiteItem(websiteCard())],
          document_correlations: [
            {
              source_id: "doc-1",
              document_title: "Final Report",
              corroborates: "GitHub implementation",
              reason: "Describes the training pipeline.",
              limitation: "Document supports the claim only.",
            },
          ],
        }),
      ],
    })

    render(<SkillReportView report={report} />)

    const summary = screen.getByTestId("recruiter-verification-access")
    expect(summary).toHaveTextContent("Recruiter verification access")
    const rows = within(summary).getAllByTestId("verification-access-row")
    expect(rows.map((r) => r.getAttribute("data-source"))).toEqual([
      "GitHub Proof",
      "Website Proof",
      "Document Proof",
    ])
    // GitHub: exact code lines exist → original available.
    expect(rows[0]).toHaveAttribute("data-state", "original_available")
    expect(rows[0]).toHaveTextContent("exact code lines")
    // Website: local/private with frames → recorded evidence, never "live".
    expect(rows[1]).toHaveAttribute("data-state", "recorded_evidence")
    // Document: original not retained → verified excerpts only.
    expect(rows[2]).toHaveAttribute("data-state", "excerpts_only")
    expect(rows[2]).toHaveTextContent("not retained")
    // Absent sources yield no row — nothing is invented.
    expect(
      rows.find((r) => r.getAttribute("data-source") === "Project Defense"),
    ).toBeUndefined()
  })

  it("renders nothing when the report names no proof source", () => {
    render(<SkillReportView report={skillReport()} />)
    expect(screen.queryByTestId("recruiter-verification-access")).not.toBeInTheDocument()
  })

  it("marks a public live website as directly verifiable", () => {
    const rows = deriveVerificationAccessRows(
      skillReport({
        proof_chains: [
          chain({
            sources: ["Website Proof"],
            website_evidence: [
              websiteItem(
                websiteCard({
                  is_public_live_url: true,
                  is_local_or_private_url: false,
                  open_website_url: "https://demo.example.com",
                  verification_mode: "directly_verifiable_live",
                }),
              ),
            ],
          }),
        ],
      }),
    )
    expect(rows).toEqual([
      expect.objectContaining({ source: "Website Proof", state: "original_available" }),
    ])
    expect(rows[0].note).toMatch(/live/i)
  })
})

// ── Per-chain Original proof access strip ─────────────────────────────────────

describe("Chain original proof access strip", () => {
  it("shows live-URL access for a public website proof", () => {
    const report = skillReport({
      proof_chains: [
        chain({
          sources: ["Website Proof"],
          website_evidence: [
            websiteItem(
              websiteCard({
                is_public_live_url: true,
                is_local_or_private_url: false,
                open_website_url: "https://demo.example.com",
                verification_mode: "directly_verifiable_live",
                verification_mode_label: "Directly verifiable live",
                deployment_recommended: false,
              }),
              { public_url: "https://demo.example.com", public_safe: true },
            ),
          ],
        }),
      ],
    })
    render(<SkillReportView report={report} />)

    const strip = screen.getByTestId("chain-original-proof-access")
    const row = within(strip).getByTestId("original-access-row")
    expect(row).toHaveAttribute("data-source", "Website Proof")
    expect(row).toHaveAttribute("data-state", "original_available")
    expect(row).toHaveTextContent("recruiter can open the current deployment")
    // Live proof → no frames gallery button in the strip.
    expect(within(strip).queryByTestId("website-frames-view-button")).not.toBeInTheDocument()
  })

  it("never upgrades a local/private website proof to live access", () => {
    const rows = deriveChainAccessRows(
      chain({
        sources: ["Website Proof"],
        website_evidence: [websiteItem(websiteCard())],
      }),
    )
    expect(rows).toEqual([
      expect.objectContaining({ source: "Website Proof", state: "recorded_evidence" }),
    ])
    expect(rows[0].note).toMatch(/local\/private runtime/)
    expect(rows[0].note).toMatch(/cannot be opened/)
  })

  it("shows an honest no-access row for a website proof without frames", () => {
    const report = skillReport({
      proof_chains: [
        chain({
          sources: ["Website Proof"],
          website_evidence: [
            websiteItem(websiteCard({ screenshot_available: false, screenshot_access_label: "unavailable" })),
          ],
        }),
      ],
    })
    render(<SkillReportView report={report} />)

    const strip = screen.getByTestId("chain-original-proof-access")
    const row = within(strip).getByTestId("original-access-row")
    expect(row).toHaveAttribute("data-state", "no_original_access")
    expect(row).toHaveTextContent("no captured frames")
    expect(screen.queryByTestId("website-frames-view-button")).not.toBeInTheDocument()
  })

  it("keeps the document row on verified excerpts when the file is not retained", () => {
    const report = skillReport({
      proof_chains: [
        chain({
          sources: ["Document Proof"],
          document_correlations: [
            {
              source_id: "doc-1",
              document_title: "Final Report",
              corroborates: "GitHub implementation",
              reason: "Describes the training pipeline.",
              limitation: "Document supports the claim only.",
            },
          ],
        }),
      ],
    })
    render(<SkillReportView report={report} />)

    const row = screen.getByTestId("original-access-row")
    expect(row).toHaveAttribute("data-source", "Document Proof")
    expect(row).toHaveAttribute("data-state", "excerpts_only")
    expect(row).toHaveTextContent(
      "Original document was not retained after analysis; VeriBridge stores verified excerpts and locators.",
    )
    // No fake download affordance anywhere.
    expect(screen.queryByTestId("document-inspection-download")).not.toBeInTheDocument()
    expect(screen.queryByText(/download/i)).not.toBeInTheDocument()
  })

  it("marks the document original available only when the backend gated a safe download open", () => {
    const rows = deriveChainAccessRows(
      chain({
        sources: ["Document Proof"],
        document_correlations: [
          {
            source_id: "doc-1",
            document_title: "Final Report",
            corroborates: "GitHub implementation",
            reason: "Shared for review.",
            limitation: "",
            inspection_card: {
              title: "Final Report",
              evidence_role: "Supporting evidence",
              why_supported: "Describes the pipeline.",
              limitation: "",
              access_note: "The candidate shared this document for recruiter review.",
              can_download_document: true,
              document_download_url: "https://cdn.veribridge.app/docs/final-report.pdf",
              is_public_safe: true,
              is_attached_to_project: true,
            },
          },
        ],
      }),
    )
    expect(rows).toEqual([
      expect.objectContaining({ source: "Document Proof", state: "original_available" }),
    ])
  })
})

// ── Website frames gallery (owner-only) ───────────────────────────────────────

describe("Website captured-frames gallery", () => {
  it("streams frames through the authorized proxy for the owner of a recorded-only proof", async () => {
    vi.mocked(listWebsiteProofFrames).mockResolvedValue({
      session_id: "sess-web-1",
      frame_count: 2,
      frames: [
        { frame_id: "f-1", frame_type: "video_keyframe", timestamp_ms: 0, timestamp_label: "0:00", has_thumbnail: true },
        { frame_id: "f-2", frame_type: "video_keyframe", timestamp_ms: 65000, timestamp_label: "1:05", has_thumbnail: true },
      ],
    })
    vi.mocked(fetchFrameThumbnailObjectUrl).mockImplementation(async (id: string) => `blob:frame-${id}`)

    const report = skillReport({
      proof_chains: [
        chain({ sources: ["Website Proof"], website_evidence: [websiteItem(websiteCard())] }),
      ],
    })
    render(<SkillReportView report={report} />)

    // The strip offers the honest recorded-workflow access…
    const strip = screen.getByTestId("chain-original-proof-access")
    const button = within(strip).getByTestId("website-frames-view-button")
    expect(button).toHaveTextContent("View captured frames")
    fireEvent.click(button)

    // …and the gallery renders the proxied frames with timestamps.
    const gallery = await within(strip).findByTestId("website-frames-gallery")
    const frames = within(gallery).getAllByTestId("website-frame")
    expect(frames).toHaveLength(2)
    expect(within(frames[0]).getByRole("img")).toHaveAttribute("src", "blob:frame-f-1")
    expect(frames[1]).toHaveTextContent("1:05")
    expect(listWebsiteProofFrames).toHaveBeenCalledWith("sess-web-1")
    // No storage path or signed URL ever reaches the DOM.
    expect(document.body.innerHTML).not.toContain("frame-evidence/")
    expect(document.body.innerHTML).not.toContain("supabase")
  })

  it("fails soft to an honest note when frames cannot be loaded", async () => {
    vi.mocked(listWebsiteProofFrames).mockRejectedValue(new Error("network"))

    const report = skillReport({
      proof_chains: [
        chain({ sources: ["Website Proof"], website_evidence: [websiteItem(websiteCard())] }),
      ],
    })
    render(<SkillReportView report={report} />)

    const strip = screen.getByTestId("chain-original-proof-access")
    fireEvent.click(within(strip).getByTestId("website-frames-view-button"))
    expect(await within(strip).findByTestId("website-frames-unavailable")).toHaveTextContent(
      "could not be loaded",
    )
  })

  it("says so honestly when no viewable frames were stored", async () => {
    vi.mocked(listWebsiteProofFrames).mockResolvedValue({
      session_id: "sess-web-1",
      frame_count: 1,
      frames: [{ frame_id: "f-1", frame_type: "video_keyframe", timestamp_ms: 0, timestamp_label: "0:00", has_thumbnail: false }],
    })

    const report = skillReport({
      proof_chains: [
        chain({ sources: ["Website Proof"], website_evidence: [websiteItem(websiteCard())] }),
      ],
    })
    render(<SkillReportView report={report} />)

    const strip = screen.getByTestId("chain-original-proof-access")
    fireEvent.click(within(strip).getByTestId("website-frames-view-button"))
    expect(await within(strip).findByTestId("website-frames-unavailable")).toHaveTextContent(
      "No viewable frames were stored",
    )
    expect(fetchFrameThumbnailObjectUrl).not.toHaveBeenCalled()
  })

  it("renders the owner frames gallery inside the Website Runtime Inspection card too", () => {
    const report = skillReport({
      proof_chains: [
        chain({ sources: ["Website Proof"], website_evidence: [websiteItem(websiteCard())] }),
      ],
    })
    render(<SkillReportView report={report} />)

    const card = screen.getByTestId("website-evidence-card")
    expect(within(card).getByTestId("website-frames-view-button")).toBeInTheDocument()
    // The permission-gated status line is for non-owner surfaces only.
    expect(within(card).queryByTestId("website-screenshot-status")).not.toBeInTheDocument()
  })
})

// ── Defense transcript viewer (owner-only) ────────────────────────────────────

describe("Defense transcript access", () => {
  it("lets the owner open the defense transcript and highlights cited moments", async () => {
    vi.mocked(getVBRSessionTranscript).mockResolvedValue(TRANSCRIPT)

    const report = skillReport({ proof_chains: [defenseGroupChain()] })
    render(<SkillReportView report={report} />)

    const strip = screen.getByTestId("chain-original-proof-access")
    const row = within(strip).getByTestId("original-access-row")
    expect(row).toHaveAttribute("data-source", "Project Defense")
    expect(row).toHaveAttribute("data-state", "transcript_available")

    fireEvent.click(within(strip).getByTestId("defense-transcript-view-button"))
    const viewer = await within(strip).findByTestId("defense-transcript-viewer")
    const segments = within(viewer).getAllByTestId("defense-transcript-segment")
    expect(segments).toHaveLength(2)
    // The cited moment (0:45) falls inside the second segment (40s–60s).
    expect(segments[0]).toHaveAttribute("data-cited", "false")
    expect(segments[1]).toHaveAttribute("data-cited", "true")
    expect(within(segments[1]).getByTestId("defense-transcript-cited-chip")).toBeInTheDocument()
    expect(getVBRSessionTranscript).toHaveBeenCalledWith("sess-def-1")
  })

  it("fails soft to an honest note when the transcript cannot be loaded", async () => {
    vi.mocked(getVBRSessionTranscript).mockRejectedValue(new Error("boom"))

    render(<SkillReportView report={skillReport({ proof_chains: [defenseGroupChain()] })} />)

    fireEvent.click(screen.getByTestId("defense-transcript-view-button"))
    expect(await screen.findByTestId("defense-transcript-unavailable")).toHaveTextContent(
      "could not be loaded",
    )
  })

  it("upgrades the defense row to recorded evidence when an authorized recording exists", () => {
    const rows = deriveChainAccessRows(
      defenseGroupChain({
        project_defense_inspection: [
          {
            evidence_id_safe: "pdi-1",
            video_available: true,
            video_playback_url: "https://signed.example.com/video",
            transcript_excerpt_available: true,
          },
        ],
      }),
    )
    expect(rows).toEqual([
      expect.objectContaining({ source: "Project Defense", state: "recorded_evidence" }),
    ])
    expect(rows[0].note).toMatch(/recording and transcript/i)
  })

  it("shows timestamped video access without inventing a player", () => {
    const report = skillReport({
      proof_chains: [
        chain({
          sources: ["Video Evidence"],
          video_evidence: [
            {
              proof_type: "Video Evidence",
              source_id: "sess-def-1",
              title: "Model demo walkthrough",
              safe_summary: "Demonstrated the prediction flow.",
              public_safe: false,
              is_attached_to_project: true,
              attached_project_ids: ["proj-1"],
              project_titles: [],
              limitation: "",
              workflow_steps: [],
              timestamp_label: "2:10",
            } as SkillReport["video"][number],
          ],
        }),
      ],
    })
    render(<SkillReportView report={report} />)

    const strip = screen.getByTestId("chain-original-proof-access")
    const row = within(strip).getByTestId("original-access-row")
    expect(row).toHaveAttribute("data-source", "Video Evidence")
    expect(row).toHaveAttribute("data-state", "recorded_evidence")
    expect(row).toHaveTextContent("Timestamped video moments")
    // No fabricated media player — playback only exists where the backend
    // supplied an authorized URL (the defense inspection cards).
    expect(document.querySelector("video")).toBeNull()
  })
})

// ── Fail-closed behaviour ─────────────────────────────────────────────────────

describe("Fail-closed original access", () => {
  it("public surface never renders owner-only frame or transcript access", () => {
    const report = skillReport({
      proof_chains: [
        chain({ sources: ["Website Proof"], website_evidence: [websiteItem(websiteCard())] }),
        defenseGroupChain({ project_id: "proj-2", project_title: "Second project" }),
      ],
    })
    render(<SkillReportView report={report} publicSafe />)

    // The honest access rows still render (labels only)…
    expect(screen.getAllByTestId("chain-original-proof-access").length).toBeGreaterThan(0)
    // …but no owner-only artifact affordances do.
    expect(screen.queryByTestId("website-frames-view-button")).not.toBeInTheDocument()
    expect(screen.queryByTestId("defense-transcript-view-button")).not.toBeInTheDocument()
    // Non-owner keeps the permission-gated screenshot status inside the card.
    expect(screen.getByTestId("website-screenshot-status")).toBeInTheDocument()
  })

  it("renders no access strip when a chain names no proof source", () => {
    render(<SkillReportView report={skillReport({ proof_chains: [chain()] })} />)
    expect(screen.queryByTestId("chain-original-proof-access")).not.toBeInTheDocument()
  })

  it("defense summary-only chains offer no transcript button", () => {
    const report = skillReport({
      proof_chains: [
        chain({
          sources: ["Project Defense"],
          defense_group: {
            explanation: "The candidate discussed the project.",
            moments: [],
            grouped_count: 1,
            limitation: "Explanation evidence only.",
            source_ids: [],
          },
        }),
      ],
    })
    render(<SkillReportView report={report} />)

    const row = screen.getByTestId("original-access-row")
    expect(row).toHaveAttribute("data-source", "Project Defense")
    expect(row).toHaveAttribute("data-state", "no_original_access")
    expect(screen.queryByTestId("defense-transcript-view-button")).not.toBeInTheDocument()
  })
})
