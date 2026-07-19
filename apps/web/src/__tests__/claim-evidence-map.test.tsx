/**
 * Canonical Claim-to-Evidence Map — frontend rendering tests.
 *
 * The component renders EXACTLY what the backend synthesized: counted vs
 * not-counted flags, identity-mismatch warnings, pending-defense states,
 * canonical video descriptors, document retention states, corroboration
 * groups, and gaps. It never infers a relationship or invents a citation —
 * missing/legacy data renders nothing rather than a guess.
 */

import { render, screen, within, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"

import { ClaimEvidenceMapSection } from "../../components/passport/ClaimEvidenceMapSection"
import type {
  CanonicalEvidenceCitation,
  CanonicalSkillClaim,
  ClaimEvidenceMap,
} from "@/lib/vbr-api"

vi.mock("@/lib/api", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api")>()),
  fetchAPI: vi.fn(),
}))

import { fetchAPI } from "@/lib/api"

const BOSTON = "Boston Smart Accident Risk Rerouting"

function makeClaim(overrides: Partial<CanonicalSkillClaim> = {}): CanonicalSkillClaim {
  return {
    id: "claim-1",
    project_id: "p1",
    skill_id: "machine-learning",
    skill_name: "Machine Learning",
    claim_text: `Machine Learning was implemented and demonstrated in ${BOSTON}.`,
    claim_scope: "project",
    feature_ids: [],
    qualitative_status: "Partially demonstrated",
    strongest_evidence_tier: "Primary implementation",
    limitations: [],
    ...overrides,
  }
}

function makeCitation(overrides: Partial<CanonicalEvidenceCitation> = {}): CanonicalEvidenceCitation {
  return {
    evidence_id: "ev-1",
    proof_type: "GitHub Proof",
    project_id: "p1",
    skill_id: "machine-learning",
    claim_id: "claim-1",
    feature_id: null,
    source_title: "octocat/boston-rerouting",
    source_locator: null,
    explanation: "Fits the risk classifier on the training set.",
    relevance: "Trains the accident-risk model used by the rerouting API.",
    strength: "Primary implementation",
    identity_reasons: [],
    counted_as_direct_evidence: true,
    limitations: [],
    ...overrides,
  }
}

function makeMap(overrides: Partial<ClaimEvidenceMap> = {}): ClaimEvidenceMap {
  return {
    schema_version: 1,
    scope: "skill_report",
    skill_name: "Machine Learning",
    project_id: null,
    claims: [makeClaim()],
    features: [],
    citations: [makeCitation()],
    relations: [],
    corroborations: [],
    contradictions: [],
    gaps: [],
    recruiter_actions: [],
    limitations: [],
    ...overrides,
  }
}

describe("ClaimEvidenceMapSection", () => {
  it("renders nothing for legacy payloads (null map or no claims) — never guesses", () => {
    const { container: nullMap } = render(<ClaimEvidenceMapSection map={null} />)
    expect(nullMap.innerHTML).toBe("")
    const { container: emptyMap } = render(<ClaimEvidenceMapSection map={makeMap({ claims: [], citations: [] })} />)
    expect(emptyMap.innerHTML).toBe("")
  })

  it("renders the claim with its qualitative status and strongest tier", () => {
    render(<ClaimEvidenceMapSection map={makeMap()} />)
    expect(screen.getByTestId("claim-evidence-map")).toBeInTheDocument()
    expect(screen.getByText(`Machine Learning was implemented and demonstrated in ${BOSTON}.`)).toBeInTheDocument()
    expect(within(screen.getByTestId("cem-claim-status")).getByText("Partially demonstrated")).toBeInTheDocument()
    expect(screen.getByText(/Strongest evidence: Primary implementation/)).toBeInTheDocument()
  })

  it("renders an exact GitHub citation: file, lines, symbol, commit, excerpt, link", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              file_path: "train.py",
              start_line: 41,
              end_line: 58,
              symbol_name: "train_model",
              commit_sha: "abc123def4567890",
              code_excerpt: "model.fit(X_train, y_train)",
              access: {
                kind: "github_lines",
                label: "Open exact lines on GitHub",
                available: true,
                action_label: "View code",
                url: "https://github.com/octocat/boston-rerouting/blob/main/train.py#L41-L58",
              },
            }),
          ],
        })}
      />,
    )
    expect(screen.getByTestId("cem-citation-locator").textContent).toBe(
      "train.py · L41–L58 · train_model() · abc123def4",
    )
    expect(screen.getByTestId("cem-code-excerpt").textContent).toContain("model.fit(X_train, y_train)")
    const link = screen.getByTestId("cem-access-link")
    expect(link).toHaveAttribute("href", expect.stringContaining("#L41-L58"))
    expect(screen.getByText("Counted as direct evidence")).toBeInTheDocument()
  })

  it("shows the analyzed-context window honestly beside unchanged target lines", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              file_path: "scripts/pipeline_retrain.py",
              start_line: 51,
              end_line: 52,
              symbol_name: "retrain",
              context_start_line: 38,
              context_end_line: 67,
            }),
          ],
        })}
      />,
    )
    // Target citation is never rewritten to pretend the wider window was cited.
    expect(screen.getByTestId("cem-citation-locator").textContent).toContain("L51–L52")
    const ctx = screen.getByTestId("cem-analyzed-context")
    expect(ctx.textContent).toContain("Analyzed context: L38–L67")
    expect(ctx.textContent).toContain("retrain")
  })

  it("omits the analyzed-context line when it matches the target lines", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              file_path: "train.py",
              start_line: 46,
              end_line: 61,
              context_start_line: 46,
              context_end_line: 61,
            }),
          ],
        })}
      />,
    )
    expect(screen.queryByTestId("cem-analyzed-context")).not.toBeInTheDocument()
  })

  it("renders an unknown-purpose row as not counted (countability contract)", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              strength: "Weak signal",
              github_tier: "weak_signal",
              counted_as_direct_evidence: false,
              explanation:
                "Insufficient context to classify this code block; the stored snippet needs reanalysis with its containing symbol or a larger window.",
            }),
          ],
        })}
      />,
    )
    expect(screen.getByText("Context only — not counted")).toBeInTheDocument()
    expect(screen.queryByText("Counted as direct evidence")).not.toBeInTheDocument()
  })

  it("never invents a locator when the backend sent none", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              strength: "Weak signal",
              counted_as_direct_evidence: false,
              limitations: ["No file/line-level code citation is stored for this row."],
            }),
          ],
        })}
      />,
    )
    expect(screen.queryByTestId("cem-citation-locator")).not.toBeInTheDocument()
    expect(screen.queryByTestId("cem-access-link")).not.toBeInTheDocument()
    expect(screen.getByText("Context only — not counted")).toBeInTheDocument()
    expect(screen.getByText(/No file\/line-level code citation/)).toBeInTheDocument()
  })

  it("shows a visible mismatch warning that is explicitly not counted", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          claims: [makeClaim({ qualitative_status: "Mismatch detected" })],
          citations: [
            makeCitation({
              evidence_id: "ev-web",
              proof_type: "Website Proof",
              source_title: "Recorded session",
              strength: "Context only",
              identity_state: "mismatched",
              identity_reasons: [
                "The recorded application identifies as 'VeriBridge AI', which does not match this project.",
              ],
              counted_as_direct_evidence: false,
            }),
          ],
          contradictions: [
            {
              contradiction_id: "contra-1",
              kind: "identity_mismatch",
              claim_id: "claim-1",
              evidence_ids: ["ev-web"],
              description: `A website recording attached to '${BOSTON}' identifies as a different application.`,
              recommended_action: "Review this recording in the Proof Vault: detach, reassign, or confirm it.",
            },
          ],
        })}
      />,
    )
    const citation = screen.getByTestId("cem-citation")
    expect(citation.getAttribute("data-counted")).toBe("false")
    expect(citation.getAttribute("data-identity")).toBe("mismatched")
    const warning = screen.getByTestId("cem-mismatch-warning")
    expect(warning.textContent).toContain("VeriBridge AI")
    expect(screen.getByText("Mismatch — not counted")).toBeInTheDocument()
    // The global contradictions section names the owner action; nothing is deleted.
    expect(screen.getByTestId("cem-contradiction").textContent).toContain("detach, reassign, or confirm")
    expect(within(screen.getByTestId("cem-claim-status")).getByText("Mismatch detected")).toBeInTheDocument()
  })

  it("shows possible-match recordings as needs-review and not counted", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              proof_type: "Website Proof",
              strength: "Context only",
              identity_state: "possible_match_review",
              identity_reasons: ["The recording carries no application-identity signals."],
              counted_as_direct_evidence: false,
            }),
          ],
        })}
      />,
    )
    expect(screen.getByText("Needs review — not counted")).toBeInTheDocument()
    expect(screen.getByTestId("cem-identity-review").textContent).toContain("no application-identity signals")
  })

  it("renders the pending-defense state without counting it", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          claims: [makeClaim({ qualitative_status: "Analysis pending" })],
          citations: [
            makeCitation({
              proof_type: "Project Defense",
              source_title: `Project Defense — ${BOSTON}`,
              strength: "Analysis pending",
              analysis_pending: true,
              counted_as_direct_evidence: false,
              explanation: "Defense captured, analysis pending.",
            }),
          ],
        })}
      />,
    )
    expect(screen.getByText("Analysis pending — not counted")).toBeInTheDocument()
    expect(screen.getByTestId("cem-pending").textContent).toContain("Defense captured, analysis pending")
  })

  it("renders a canonical video descriptor with cited segments and a player when authorized", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              proof_type: "Project Defense",
              question_text: "How did you train and validate the accident-risk model?",
              transcript_excerpt: "We trained a random forest on three years of crash data…",
              timestamp_start_label: "02:10",
              timestamp_end_label: "02:41",
              video: {
                proof_type: "Project Defense",
                recording_available: true,
                availability: "retained",
                duration_label: "12:04",
                mime_type: "video/webm",
                transcript_available: true,
                poster_available: false,
                timeline_events: [],
                cited_segments: [
                  { start_label: "02:10", end_label: "02:41", description: "Explains model training and validation" },
                ],
                access: {
                  kind: "defense_recording",
                  label: "Play defense recording",
                  available: true,
                  action_label: "Play recording",
                  url: "/api/v1/defense/recording/owner-authorized",
                  requires_owner_permission: true,
                },
                limitations: [],
              },
            }),
          ],
        })}
      />,
    )
    const video = screen.getByTestId("cem-video")
    expect(video.getAttribute("data-availability")).toBe("retained")
    expect(screen.getByText("Recording retained")).toBeInTheDocument()
    expect(screen.getByTestId("cem-video-player")).toBeInTheDocument()
    expect(screen.getByTestId("cem-video-segments").textContent).toContain("02:10–02:41")
    expect(screen.getByText(/Q:/)).toBeInTheDocument()
    expect(screen.getByTestId("cem-excerpt").textContent).toContain("random forest")
  })

  it("renders honest not-retained video state with no player", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              proof_type: "Website Proof",
              identity_state: "matched_direct",
              video: {
                proof_type: "Website Proof",
                recording_available: false,
                availability: "not_retained",
                transcript_available: false,
                timeline_events: [{ timestamp_label: null, description: "User submits route inputs" }],
                cited_segments: [],
                limitations: ["The session video was not retained by this pipeline version."],
              },
            }),
          ],
        })}
      />,
    )
    expect(screen.getByText("Recording not retained")).toBeInTheDocument()
    expect(screen.queryByTestId("cem-video-player")).not.toBeInTheDocument()
    expect(screen.getByTestId("cem-video-timeline").textContent).toContain("User submits route inputs")
    expect(screen.getByText(/was not retained/)).toBeInTheDocument()
  })

  it("renders document retention states: excerpts-only vs open/download", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              evidence_id: "ev-doc-old",
              proof_type: "Document Proof",
              source_title: "Historical report",
              page_number: 5,
              section_title: "Model architecture",
              document_access: {
                retained: false,
                excerpts_only: true,
                open_available: false,
                download_available: false,
                publication_state: "private",
                limitations: ["The original file was not retained for this historical document."],
              },
            }),
            makeCitation({
              evidence_id: "ev-doc-new",
              proof_type: "Document Proof",
              source_title: "Retained report",
              page_number: 2,
              document_access: {
                retained: true,
                excerpts_only: false,
                open_available: true,
                download_available: true,
                publication_state: "published",
                limitations: [],
              },
            }),
          ],
        })}
      />,
    )
    const blocks = screen.getAllByTestId("cem-doc-access")
    expect(blocks[0].textContent).toContain("Excerpts only — original not retained")
    expect(blocks[1].textContent).toContain("Original retained")
    expect(blocks[1].textContent).toContain("Open original available")
    expect(blocks[1].textContent).toContain("Download available")
    // Page/section locators render for the document citation.
    expect(screen.getByText("Page 5 · Model architecture")).toBeInTheDocument()
  })

  it("renders block-aware document table and labels uncertain visual extraction", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              evidence_id: "doc-table",
              proof_type: "Document Proof",
              document_block: {
                document_id: "doc-1",
                document_title: "Architecture report",
                page_number: 7,
                block_type: "table",
                extracted_text: "Latency | 120 ms",
                table_cells: [["Metric", "Value"], ["Latency", "120 ms"]],
                extraction_confidence: "high",
              },
              actions: [{ kind: "document_block", label: "View block", available: true, action_label: "View source block", url: "/api/v1/proofs/artifacts/doc/view#page=7", requires_owner_permission: true }],
            }),
            makeCitation({
              evidence_id: "doc-visual",
              proof_type: "Document Proof",
              document_block: {
                document_id: "doc-2",
                document_title: "Design appendix",
                page_number: 9,
                block_type: "unknown_visual_region",
                table_cells: [],
                extraction_confidence: "not_available",
                model_limitation: "No chart values are inferred from this unclear visual.",
              },
            }),
          ],
        })}
      />,
    )
    expect(screen.getByText("[Document · page 7 · table]")).toBeInTheDocument()
    expect(screen.getByTestId("cem-document-table").textContent).toContain("120 ms")
    expect(screen.getByText("[Document · page 9 · unknown visual region]")).toBeInTheDocument()
    expect(screen.getByTestId("cem-document-block-limitation")).toHaveTextContent("No chart values are inferred")
    expect(screen.getByText(/View source block/)).toBeInTheDocument()
  })

  it("renders retained Website replay, cited moment, analysis action, and local limitation", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [
            makeCitation({
              proof_type: "Website Proof",
              citation_type: "website_video_timestamp",
              timestamp_start_label: "00:24",
              project_relationship: {
                state: "directly_linked",
                project_id: "veribridge",
                project_title: "VeriBridge",
                match_method: "explicit_project_id",
                counted: true,
                confirmed_by_user: true,
                reasons: ["Created for this project."],
              },
              video: {
                proof_type: "Website Proof",
                recording_available: true,
                availability: "retained",
                transcript_available: false,
                timeline_events: [{ timestamp_label: "00:24", description: "Submitted proof workflow" }],
                cited_segments: [{ start_label: "00:24", end_label: null, description: "Submitted proof workflow" }],
                access: { kind: "recorded_replay", label: "Replay", available: true, action_label: "Play cited moment", url: "/api/v1/proofs/website/session/replay", requires_owner_permission: true },
                limitations: ["Local/private recording: recruiters cannot independently open localhost."],
              },
              actions: [
                { kind: "recorded_replay", label: "Replay", available: true, action_label: "Play cited moment", url: "/api/v1/proofs/website/session/replay", requires_owner_permission: true },
                { kind: "website_analysis", label: "Analysis", available: true, action_label: "View analysis", url: "/student/proofs/website?session=session", requires_owner_permission: true },
              ],
            }),
          ],
        })}
      />,
    )
    expect(screen.getByTestId("cem-video-player")).toBeInTheDocument()
    expect(screen.getByTestId("cem-video-segments")).toHaveTextContent("00:24")
    expect(screen.getByText("Play cited moment →")).toBeInTheDocument()
    expect(screen.getByText("View analysis →")).toBeInTheDocument()
    expect(screen.getByText(/cannot independently open localhost/)).toBeInTheDocument()
    expect(screen.getByTestId("cem-project-relationship")).toHaveAttribute("data-state", "directly_linked")
  })

  it("renders corroboration groups with alignment reason and unique contributions", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          claims: [makeClaim({ qualitative_status: "Demonstrated" })],
          corroborations: [
            {
              group_id: "corro-1",
              claim_id: "claim-1",
              feature_id: null,
              evidence_ids: ["ev-1", "ev-2"],
              sources: ["GitHub Proof", "Website Proof"],
              alignment_reason:
                "Each source independently supports the claim — alignment is at claim level, not merely shared project attachment.",
              independent_sources: true,
              unique_contributions: [
                "GitHub Proof: shows the implementation code at exact cited lines",
                "Website Proof: shows the behaviour running at recording time",
              ],
              limitations: [],
            },
          ],
        })}
      />,
    )
    const group = screen.getByTestId("cem-corroboration")
    expect(group.textContent).toContain("GitHub Proof + Website Proof")
    expect(group.textContent).toContain("not merely shared project attachment")
    expect(group.textContent).toContain("exact cited lines")
  })

  it("renders per-claim gaps and recruiter actions", () => {
    render(
      <ClaimEvidenceMapSection
        map={makeMap({
          gaps: [
            {
              claim_id: "claim-1",
              proof_type: "Website Proof",
              description: "No Website Proof evidence supports this claim yet.",
              recommended_action: "Record a Website Proof of this project's own application.",
            },
          ],
          recruiter_actions: ["Open the exact cited lines: train.py L41–L58"],
        })}
      />,
    )
    expect(screen.getByTestId("cem-gap").textContent).toContain("No Website Proof evidence")
    expect(screen.getByTestId("cem-recruiter-actions").textContent).toContain("train.py L41–L58")
  })

  it("shows no numeric trust scores anywhere", () => {
    const { container } = render(
      <ClaimEvidenceMapSection
        map={makeMap({
          citations: [makeCitation({ code_excerpt: null })],
        })}
      />,
    )
    expect(container.textContent).not.toMatch(/\b(trust|confidence) score\b/i)
    expect(container.textContent).not.toContain("/100")
  })
})

// ── Honest source counts + grouped context + duplicate video (skill-evidence-map-fix)

describe("ClaimEvidenceMapSection — source counts and grouped context", () => {
  const counts = {
    direct: 1,
    corroborating: 1,
    context_only: 1,
    pending: 1,
    vault_only: 0,
    unsupported: 0,
    direct_sources: ["GitHub Proof"],
    corroborating_sources: ["Project Defense"],
    context_only_sources: ["Video Evidence"],
    pending_sources: ["Project Defense"],
    vault_only_sources: [],
    unsupported_sources: [],
  }

  it("renders per-claim source-count buckets with their proof types, omitting zero buckets", () => {
    render(<ClaimEvidenceMapSection map={makeMap({ claims: [makeClaim({ source_counts: counts })] })} />)
    const row = screen.getAllByTestId("cem-source-counts")[0]
    expect(within(row).getByTestId("cem-count-direct")).toHaveTextContent("Direct evidence sources: 1")
    expect(within(row).getByTestId("cem-count-direct")).toHaveTextContent("GitHub Proof")
    expect(within(row).getByTestId("cem-count-corroborating")).toHaveTextContent("Corroborating sources: 1")
    expect(within(row).getByTestId("cem-count-pending")).toHaveTextContent("Pending sources: 1")
    expect(within(row).queryByTestId("cem-count-vault")).not.toBeInTheDocument()
    expect(within(row).queryByTestId("cem-count-unsupported")).not.toBeInTheDocument()
  })

  it("renders the map-level union of the buckets", () => {
    render(<ClaimEvidenceMapSection map={makeMap({ source_counts: counts })} />)
    expect(screen.getByTestId("cem-map-source-counts")).toHaveTextContent("Proof sources across this report")
  })

  it("renders grouped weak repo context ONCE at the map level, never under a claim", () => {
    const grouped = makeCitation({
      evidence_id: "ev-weak",
      claim_id: null,
      grouped_context: true,
      counted_as_direct_evidence: false,
      github_tier: "weak_signal",
      strength: "Weak signal",
      source_title: "requirements.txt — repo-level signal",
      limitations: ["Repository-level / weak code signal — grouped once for the whole report and never counted."],
    })
    render(<ClaimEvidenceMapSection map={makeMap({ citations: [makeCitation(), grouped] })} />)
    const section = screen.getByTestId("cem-grouped-context")
    expect(section).toHaveTextContent("Grouped repository context — shown once, never counted")
    expect(within(section).getByTestId("cem-citation")).toHaveTextContent("requirements.txt")
    // The claim block does NOT repeat the weak signal.
    const claim = screen.getByTestId("cem-claim")
    expect(within(claim).queryByText(/requirements\.txt/)).not.toBeInTheDocument()
  })

  it("labels a video citation folded into the same defense recording and never as counted", () => {
    const video = makeCitation({
      evidence_id: "ev-vid",
      proof_type: "Video Evidence",
      duplicate_of_evidence_id: "ev-def",
      counted_as_direct_evidence: false,
      strength: "Context only",
      timestamp_start_label: "02:14",
    })
    render(<ClaimEvidenceMapSection map={makeMap({ citations: [makeCitation(), video] })} />)
    const videoCard = screen
      .getAllByTestId("cem-citation")
      .find((el) => el.getAttribute("data-proof-type") === "Video Evidence")!
    expect(videoCard).toHaveTextContent("Citation into the same defense recording — not a separate source")
    expect(videoCard).not.toHaveTextContent("Counted as direct evidence")
  })
})

// ── Owner-gated /api/ document actions ────────────────────────────────────────

describe("gated document original actions", () => {
  const docCitation = () =>
    makeCitation({
      proof_type: "Document Proof",
      source_title: "VeriBridge",
      actions: [
        {
          kind: "document_original",
          label: "Open original document",
          available: true,
          action_label: "Open original document",
          url: "/api/v1/proofs/artifacts/art-doc-1/view",
          requires_owner_permission: true,
        },
        {
          kind: "document_download",
          label: "Download original",
          available: true,
          action_label: "Download original",
          url: "/api/v1/proofs/artifacts/art-doc-1/download",
          requires_owner_permission: true,
        },
      ],
      document_access: {
        retained: true,
        excerpts_only: false,
        open_available: true,
        download_available: true,
        publication_state: "private",
        original_filename: "VeriBridge_Rich_Document_Proof_Test.docx",
        mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        limitations: [],
      },
    })

  it("renders /api/ document actions as gated buttons — the artifact route never appears as an href", () => {
    render(<ClaimEvidenceMapSection map={makeMap({ citations: [docCitation()] })} />)

    const buttons = screen.getAllByTestId("cem-gated-action")
    expect(buttons).toHaveLength(2)
    expect(buttons.map((b) => b.getAttribute("data-action-kind"))).toEqual([
      "document_original",
      "document_download",
    ])
    // No raw anchor to the Bearer-gated route — it could never authorize.
    expect(screen.queryByTestId("cem-access-link")).not.toBeInTheDocument()
    expect(document.body.innerHTML).not.toContain("/api/v1/proofs/artifacts/")
  })

  it("downloads through the gated route under the ORIGINAL filename", async () => {
    vi.mocked(fetchAPI).mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["docx-bytes"]),
    } as unknown as Response)
    const createSpy = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:cem-doc-url")
    const revokeSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {})
    const captured: { href: string; download: string }[] = []
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        captured.push({ href: this.href, download: this.download })
      })

    render(<ClaimEvidenceMapSection map={makeMap({ citations: [docCitation()] })} />)
    fireEvent.click(
      screen.getAllByTestId("cem-gated-action").find((b) => b.getAttribute("data-action-kind") === "document_download")!,
    )

    await waitFor(() => expect(captured).toHaveLength(1))
    expect(fetchAPI).toHaveBeenCalledWith("/api/v1/proofs/artifacts/art-doc-1/download")
    expect(captured[0].download).toBe("VeriBridge_Rich_Document_Proof_Test.docx")
    expect(captured[0].href).toContain("blob:")

    createSpy.mockRestore()
    revokeSpy.mockRestore()
    clickSpy.mockRestore()
  })

  it("shows an honest unavailable note when the gated fetch is denied", async () => {
    vi.mocked(fetchAPI).mockResolvedValue({ ok: false, status: 404 } as unknown as Response)

    render(<ClaimEvidenceMapSection map={makeMap({ citations: [docCitation()] })} />)
    fireEvent.click(
      screen.getAllByTestId("cem-gated-action").find((b) => b.getAttribute("data-action-kind") === "document_original")!,
    )

    expect(await screen.findByTestId("cem-gated-action-unavailable")).toBeInTheDocument()
  })
})
