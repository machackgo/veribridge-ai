/**
 * ProofProjectAttachPanel — the shared explicit proof→project attach flow.
 *
 * Pins the canonical contract:
 *  - default is "Keep in Proof Vault only" and performs NO mutation;
 *  - attaching to an existing project requires explicit selection + a
 *    confirmation checkbox, then calls the shared finalization boundary;
 *  - "create new project" persists the canonical project FIRST, then
 *    finalizes the proof against the returned project id;
 *  - a directly_linked proof renders the attached state and no attach UI;
 *  - GitHub confirmation copy never claims authorship.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { ProofProjectAttachPanel } from "../../components/passport/ProofProjectAttachPanel"

vi.mock("@/lib/vbr-api", () => ({
  listVBRProjects: vi.fn(),
  createVBRProject: vi.fn(),
  confirmProofProjectRelationship: vi.fn(),
}))

import {
  confirmProofProjectRelationship,
  createVBRProject,
  listVBRProjects,
} from "@/lib/vbr-api"

const PROJECTS = [
  {
    id: "proj-wikitok",
    title: "WikiTok Open-Source Pipeline Test",
    repo_url: "https://github.com/IsaacGemal/wikitok",
    repo_full_name: "IsaacGemal/wikitok",
    deployed_url: null,
    head_sha: null,
    status: "draft",
    created_at: "2026-07-14T00:00:00Z",
    updated_at: "2026-07-14T00:00:00Z",
    metadata: {},
  },
]

beforeEach(() => {
  vi.mocked(listVBRProjects).mockReset().mockResolvedValue(PROJECTS as never)
  vi.mocked(createVBRProject).mockReset()
  vi.mocked(confirmProofProjectRelationship).mockReset()
})

describe("ProofProjectAttachPanel", () => {
  it("defaults to vault-only and performs no mutation", () => {
    render(
      <ProofProjectAttachPanel proofType="github" proofId="gh-1" onAttached={vi.fn()} />,
    )
    expect(screen.getByTestId("proof-attach-panel")).toHaveAttribute("data-state", "unattached")
    expect(screen.getByTestId("proof-attach-mode-vault")).toBeChecked()
    // No project-bound mode opened ⇒ nothing fetched, nothing attached.
    expect(listVBRProjects).not.toHaveBeenCalled()
    expect(createVBRProject).not.toHaveBeenCalled()
    expect(confirmProofProjectRelationship).not.toHaveBeenCalled()
  })

  it("renders the attached state (and no attach UI) for a directly_linked proof", () => {
    render(
      <ProofProjectAttachPanel
        proofType="document"
        proofId="doc-1"
        relationshipState="directly_linked"
        attachedProjectTitle="WikiTok Open-Source Pipeline Test"
        onAttached={vi.fn()}
      />,
    )
    const panel = screen.getByTestId("proof-attach-panel")
    expect(panel).toHaveAttribute("data-state", "attached")
    expect(panel).toHaveTextContent("Attached to WikiTok Open-Source Pipeline Test")
    expect(screen.queryByTestId("proof-attach-submit")).not.toBeInTheDocument()
  })

  it("attaches to an existing project only after explicit selection + confirmation", async () => {
    const onAttached = vi.fn()
    vi.mocked(confirmProofProjectRelationship).mockResolvedValue({} as never)
    render(
      <ProofProjectAttachPanel proofType="github" proofId="gh-1" onAttached={onAttached} />,
    )

    fireEvent.click(screen.getByTestId("proof-attach-mode-existing"))
    const select = await screen.findByTestId("proof-attach-project-select")
    fireEvent.change(select, { target: { value: "proj-wikitok" } })

    // Submit stays disabled until the student confirms.
    expect(screen.getByTestId("proof-attach-submit")).toBeDisabled()
    // GitHub confirmation copy is explicit about NOT claiming authorship.
    expect(screen.getByTestId("proof-attach-confirm").closest("label")).toHaveTextContent(
      /does not by itself claim I authored the code/i,
    )
    fireEvent.click(screen.getByTestId("proof-attach-confirm"))
    fireEvent.click(screen.getByTestId("proof-attach-submit"))

    await waitFor(() =>
      expect(confirmProofProjectRelationship).toHaveBeenCalledWith({
        proof_type: "github",
        proof_id: "gh-1",
        project_id: "proj-wikitok",
      }),
    )
    expect(createVBRProject).not.toHaveBeenCalled()
    await waitFor(() => expect(onAttached).toHaveBeenCalledWith("WikiTok Open-Source Pipeline Test"))
  })

  it("creates the canonical project FIRST, then finalizes against its id", async () => {
    const onAttached = vi.fn()
    vi.mocked(createVBRProject).mockResolvedValue({
      ...PROJECTS[0],
      id: "proj-new",
      title: "WikiTok QA",
    } as never)
    vi.mocked(confirmProofProjectRelationship).mockResolvedValue({} as never)
    render(
      <ProofProjectAttachPanel
        proofType="github"
        proofId="gh-1"
        defaultProjectTitle="wikitok"
        defaultRepoUrl="https://github.com/IsaacGemal/wikitok"
        onAttached={onAttached}
      />,
    )

    fireEvent.click(screen.getByTestId("proof-attach-mode-create"))
    fireEvent.change(screen.getByTestId("proof-attach-new-title"), {
      target: { value: "WikiTok QA" },
    })
    fireEvent.click(screen.getByTestId("proof-attach-confirm"))
    fireEvent.click(screen.getByTestId("proof-attach-submit"))

    await waitFor(() =>
      expect(createVBRProject).toHaveBeenCalledWith({
        title: "WikiTok QA",
        repo_url: "https://github.com/IsaacGemal/wikitok",
      }),
    )
    await waitFor(() =>
      expect(confirmProofProjectRelationship).toHaveBeenCalledWith({
        proof_type: "github",
        proof_id: "gh-1",
        project_id: "proj-new",
      }),
    )
    // Project persisted before the proof relationship was written.
    const createOrder = vi.mocked(createVBRProject).mock.invocationCallOrder[0]
    const confirmOrder = vi.mocked(confirmProofProjectRelationship).mock.invocationCallOrder[0]
    expect(createOrder).toBeLessThan(confirmOrder)
    await waitFor(() => expect(onAttached).toHaveBeenCalledWith("WikiTok QA"))
  })

  it("shows an honest error and attaches nothing when finalization fails", async () => {
    const onAttached = vi.fn()
    vi.mocked(confirmProofProjectRelationship).mockRejectedValue(
      new Error("This document is already attached to a different project."),
    )
    render(
      <ProofProjectAttachPanel proofType="document" proofId="doc-1" onAttached={onAttached} />,
    )
    fireEvent.click(screen.getByTestId("proof-attach-mode-existing"))
    fireEvent.change(await screen.findByTestId("proof-attach-project-select"), {
      target: { value: "proj-wikitok" },
    })
    fireEvent.click(screen.getByTestId("proof-attach-confirm"))
    fireEvent.click(screen.getByTestId("proof-attach-submit"))

    expect(await screen.findByTestId("proof-attach-error")).toHaveTextContent(
      /already attached to a different project/i,
    )
    expect(onAttached).not.toHaveBeenCalled()
  })
})
