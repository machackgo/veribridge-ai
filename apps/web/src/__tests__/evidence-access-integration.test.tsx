/**
 * Evidence access integration tests — shared types, mock store, and end-to-end
 * recruiter→student flow (all via local state / localStorage mock store).
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  createAccessRequest,
  listStudentAccessRequests,
  approveAccessRequest,
  denyAccessRequest,
  revokeAccessRequest,
  clearAccessRequestStore,
  resetAccessRequestStore,
} from "../lib/mock-evidence-access-store"
import {
  evidenceLabel,
  normaliseEvidenceKey,
  fromBackendRequest,
  EVIDENCE_TYPE_KEYS,
} from "../types/evidence-access"
import { EvidenceAccessRequestModal } from "../../components/recruiter-passport/EvidenceAccessRequestModal"
import { StudentAccessRequestsPanel } from "../../components/passport/StudentAccessRequestsPanel"
import type { StudentAccessRequest } from "../../components/passport/StudentAccessRequestsPanel"

// ── 1. Shared type correctness ─────────────────────────────────────────────────

describe("Shared evidence-access types", () => {
  it("EVIDENCE_TYPE_KEYS contains the four canonical keys", () => {
    expect(EVIDENCE_TYPE_KEYS).toContain("workflow_recordings")
    expect(EVIDENCE_TYPE_KEYS).toContain("project_defense_media")
    expect(EVIDENCE_TYPE_KEYS).toContain("uploaded_documents")
    expect(EVIDENCE_TYPE_KEYS).toContain("detailed_skill_evidence")
    expect(EVIDENCE_TYPE_KEYS).toHaveLength(4)
  })

  it("evidenceLabel returns human-readable string", () => {
    expect(evidenceLabel("workflow_recordings")).toMatch(/Workflow recordings/i)
    expect(evidenceLabel("project_defense_media")).toMatch(/Project defense/i)
    expect(evidenceLabel("uploaded_documents")).toMatch(/Uploaded documents/i)
    expect(evidenceLabel("detailed_skill_evidence")).toMatch(/Detailed skill/i)
  })

  it("normaliseEvidenceKey maps legacy backend keys to canonical keys", () => {
    expect(normaliseEvidenceKey("workflow")).toBe("workflow_recordings")
    expect(normaliseEvidenceKey("project_defense")).toBe("project_defense_media")
    expect(normaliseEvidenceKey("documents")).toBe("uploaded_documents")
    expect(normaliseEvidenceKey("evidence")).toBe("detailed_skill_evidence")
    // Already-canonical keys pass through
    expect(normaliseEvidenceKey("workflow_recordings")).toBe("workflow_recordings")
  })

  it("fromBackendRequest maps backend shape to shared type", () => {
    const backend = {
      id: "req-abc",
      requester_name: "Jane Smith",
      requester_email: "jane@co.com",
      requester_organization: "Acme",
      requester_role: "Recruiter",
      request_reason: "Testing",
      requested_sections: ["workflow_recordings"],
      status: "pending",
      created_at: "2026-01-01T00:00:00Z",
      decided_at: null,
      expires_at: null,
    }
    const r = fromBackendRequest(backend)
    expect(r.id).toBe("req-abc")
    expect(r.requesterName).toBe("Jane Smith")
    expect(r.requesterEmail).toBe("jane@co.com")
    expect(r.company).toBe("Acme")
    expect(r.role).toBe("Recruiter")
    expect(r.requestedEvidenceTypes).toEqual(["workflow_recordings"])
    expect(r.status).toBe("pending")
  })
})

// ── 2. Mock store operations ───────────────────────────────────────────────────

describe("mock-evidence-access-store", () => {
  beforeEach(() => { clearAccessRequestStore() })

  it("listStudentAccessRequests returns sample requests when store is empty", () => {
    const requests = listStudentAccessRequests()
    expect(requests.length).toBeGreaterThan(0)
    // Sample data should include a Stripe pending request
    const pending = requests.filter((r) => r.status === "pending")
    expect(pending.length).toBeGreaterThan(0)
  })

  it("createAccessRequest persists to store and is visible via list", () => {
    const req = createAccessRequest(
      {
        requesterName: "Test Recruiter",
        requesterEmail: "test@co.com",
        company: "Test Corp",
        role: "Hiring Manager",
        reason: "Test reason",
        requestedEvidenceTypes: ["workflow_recordings", "detailed_skill_evidence"],
        messageToStudent: "",
      },
      "some-passport-slug",
    )
    expect(req.id).toBeTruthy()
    expect(req.status).toBe("pending")
    const stored = listStudentAccessRequests()
    expect(stored.find((r) => r.id === req.id)).toBeTruthy()
  })

  it("approveAccessRequest changes status to approved and records approved sections", () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@x.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
    )
    const updated = approveAccessRequest(req.id, ["workflow_recordings"])
    expect(updated?.status).toBe("approved")
    expect(updated?.approvedEvidenceTypes).toEqual(["workflow_recordings"])
    expect(listStudentAccessRequests().find((r) => r.id === req.id)?.status).toBe("approved")
  })

  it("denyAccessRequest changes status to denied and persists", () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@x.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
    )
    denyAccessRequest(req.id)
    expect(listStudentAccessRequests().find((r) => r.id === req.id)?.status).toBe("denied")
  })

  it("revokeAccessRequest changes status to revoked and persists", () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@x.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    revokeAccessRequest(req.id)
    expect(listStudentAccessRequests().find((r) => r.id === req.id)?.status).toBe("revoked")
  })

  it("resetAccessRequestStore restores sample data", () => {
    // Create a request and clear
    createAccessRequest(
      { requesterName: "X", requesterEmail: "x@y.com", company: "", role: "", reason: "", requestedEvidenceTypes: [], messageToStudent: "" },
    )
    resetAccessRequestStore()
    const restored = listStudentAccessRequests()
    expect(restored.some((r) => r.requesterName === "Stripe Early Talent")).toBe(true)
  })
})

// ── 3. Recruiter modal submits → onRequestCreated called ──────────────────────

describe("EvidenceAccessRequestModal — onRequestCreated callback", () => {
  it("calls onRequestCreated with form data after mock submission", async () => {
    const onCreated = vi.fn()
    render(
      <EvidenceAccessRequestModal
        onClose={vi.fn()}
        onSubmit={async (data) => { onCreated(data) }}
      />,
    )
    fireEvent.change(screen.getByPlaceholderText("Jane Smith"), { target: { value: "Alice Recruiter" } })
    fireEvent.change(screen.getByPlaceholderText("jane@company.com"), { target: { value: "alice@co.com" } })
    fireEvent.click(screen.getByText("Submit request"))
    await waitFor(() => expect(onCreated).toHaveBeenCalled(), { timeout: 2000 })
    const arg = onCreated.mock.calls[0][0]
    expect(arg.requester_name).toBe("Alice Recruiter")
    expect(arg.requester_email).toBe("alice@co.com")
    expect(Array.isArray(arg.requested_sections)).toBe(true)
  })
})

// ── 4. Student panel external callbacks ───────────────────────────────────────

describe("StudentAccessRequestsPanel — external approve/deny/revoke callbacks", () => {
  function makePendingRequest(): StudentAccessRequest {
    return {
      id: "ext-001",
      requester_name: "Ext Recruiter",
      requester_email: "ext@co.com",
      requested_sections: ["workflow_recordings", "detailed_skill_evidence"],
      status: "pending",
      requested_at: new Date().toISOString(),
    }
  }

  it("calls onApprove callback with id and sections when confirmed", () => {
    const onApprove = vi.fn()
    render(<StudentAccessRequestsPanel requests={[makePendingRequest()]} onApprove={onApprove} />)
    fireEvent.click(screen.getByTestId("approve-btn-ext-001"))
    fireEvent.click(screen.getByText("Approve selected access"))
    expect(onApprove).toHaveBeenCalledWith("ext-001", expect.any(Array))
  })

  it("calls onDeny callback with id when denied", () => {
    const onDeny = vi.fn()
    render(<StudentAccessRequestsPanel requests={[makePendingRequest()]} onDeny={onDeny} />)
    fireEvent.click(screen.getByTestId("deny-btn-ext-001"))
    fireEvent.click(screen.getByText("Deny request"))
    expect(onDeny).toHaveBeenCalledWith("ext-001")
  })

  it("calls onRevoke callback with id when revoked", () => {
    const onRevoke = vi.fn()
    const approved: StudentAccessRequest = { ...makePendingRequest(), id: "ext-002", status: "approved" }
    render(<StudentAccessRequestsPanel requests={[approved]} onRevoke={onRevoke} />)
    fireEvent.click(screen.getByTestId("revoke-btn-ext-002"))
    fireEvent.click(screen.getByText("Revoke access"))
    expect(onRevoke).toHaveBeenCalledWith("ext-002")
  })
})

// ── 5. Privacy — no private field names rendered ───────────────────────────────

describe("Privacy — no private field names in rendered output", () => {
  it("StudentAccessRequestsPanel does not expose private fields", () => {
    const { container } = render(<StudentAccessRequestsPanel requests={[]} />)
    const html = container.innerHTML
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("raw_risk")
    expect(html).not.toContain("debug_metadata")
    expect(html).not.toContain("admin_notes")
  })

  it("EvidenceAccessRequestModal does not expose private fields", () => {
    const { container } = render(<EvidenceAccessRequestModal onClose={vi.fn()} />)
    const html = container.innerHTML
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("transcript_text")
  })

  it("privacy callout is still rendered in StudentAccessRequestsPanel", () => {
    render(<StudentAccessRequestsPanel requests={[]} />)
    expect(screen.getByTestId("privacy-callout")).toBeInTheDocument()
    expect(screen.getByText(/You control who sees your protected evidence/i)).toBeInTheDocument()
  })
})
