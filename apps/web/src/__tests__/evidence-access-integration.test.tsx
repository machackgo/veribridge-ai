/**
 * Evidence access integration tests — shared types, mock store, and end-to-end
 * recruiter→student flow (all via local state / localStorage mock store).
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  createAccessRequest,
  listStudentAccessRequests,
  approveAccessRequest,
  denyAccessRequest,
  revokeAccessRequest,
  clearAccessRequestStore,
  resetAccessRequestStore,
  clearMockEvidenceAccessRequests,
  DEMO_PASSPORT_SLUG,
} from "../lib/mock-evidence-access-store"
import {
  evidenceLabel,
  normaliseEvidenceKey,
  fromBackendRequest,
  EVIDENCE_TYPE_KEYS,
} from "../types/evidence-access"
import { EvidenceAccessRequestModal } from "../../components/recruiter-passport/EvidenceAccessRequestModal"
import { StudentAccessRequestsPanel } from "../../components/passport/StudentAccessRequestsPanel"
import { RecruiterWorkPassportPreview } from "../../components/recruiter-passport/RecruiterWorkPassportPreview"
import type { StudentAccessRequest } from "../../components/passport/StudentAccessRequestsPanel"
import type { RecruiterPassportViewResponse } from "../lib/passport-api"

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

// ── 2b. Canonical slug + upsert behaviour ─────────────────────────────────────

describe("mock-evidence-access-store — canonical slug and upsert", () => {
  beforeEach(() => { clearAccessRequestStore() })

  it("DEMO_PASSPORT_SLUG is exported and sample data uses it", () => {
    expect(typeof DEMO_PASSPORT_SLUG).toBe("string")
    expect(DEMO_PASSPORT_SLUG.length).toBeGreaterThan(0)
    const samples = listStudentAccessRequests()
    expect(samples.every((r) => r.passportSlug === DEMO_PASSPORT_SLUG)).toBe(true)
  })

  it("createAccessRequest upserts when same recruiterEmail+passportSlug already exists", () => {
    const req1 = createAccessRequest(
      {
        requesterName: "R First",
        requesterEmail: "upsert@co.com",
        company: "Co",
        role: "Recruiter",
        reason: "First submit",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      "upsert-test-slug",
    )
    const req2 = createAccessRequest(
      {
        requesterName: "R Updated",
        requesterEmail: "upsert@co.com",
        company: "Co",
        role: "Recruiter",
        reason: "Re-submit",
        requestedEvidenceTypes: ["detailed_skill_evidence"],
        messageToStudent: "Hi again",
      },
      "upsert-test-slug",
    )
    // Same ID — updated, not duplicated
    expect(req2.id).toBe(req1.id)
    expect(req2.requesterName).toBe("R Updated")
    expect(req2.requestedEvidenceTypes).toEqual(["detailed_skill_evidence"])
    expect(req2.status).toBe("pending")
    // Only one entry for this email+slug in the store
    const forSlug = listStudentAccessRequests().filter(
      (r) => r.passportSlug === "upsert-test-slug" && r.requesterEmail === "upsert@co.com",
    )
    expect(forSlug).toHaveLength(1)
  })

  it("upsert does NOT override an approved request — returns existing approved unchanged", () => {
    const req = createAccessRequest(
      {
        requesterName: "R",
        requesterEmail: "upsert2@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      "upsert-test-slug-2",
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    expect(
      listStudentAccessRequests().find((r) => r.id === req.id)?.status,
    ).toBe("approved")

    // Re-submit same recruiter — should NOT reset approved status
    const req2 = createAccessRequest(
      {
        requesterName: "R",
        requesterEmail: "upsert2@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["detailed_skill_evidence"],
        messageToStudent: "",
      },
      "upsert-test-slug-2",
    )
    // Existing approved request is returned as-is
    expect(req2.id).toBe(req.id)
    expect(req2.status).toBe("approved")
    expect(req2.approvedEvidenceTypes).toEqual(["workflow_recordings"])
    // requestedEvidenceTypes is unchanged from the approved entry
    expect(req2.requestedEvidenceTypes).toEqual(["workflow_recordings"])
  })

  it("different recruiter emails for the same slug create separate entries (no upsert)", () => {
    createAccessRequest(
      { requesterName: "R1", requesterEmail: "r1@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      "multi-recruiter-slug",
    )
    createAccessRequest(
      { requesterName: "R2", requesterEmail: "r2@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      "multi-recruiter-slug",
    )
    const forSlug = listStudentAccessRequests().filter(
      (r) => r.passportSlug === "multi-recruiter-slug",
    )
    expect(forSlug).toHaveLength(2)
  })

  it("recruiter submit with DEMO_PASSPORT_SLUG upserts over the sample-stripe entry", () => {
    // After clearAccessRequestStore, load() returns SAMPLE_REQUESTS which has
    // sample-stripe-001 with requesterEmail "recruiter@stripe.com" and DEMO_PASSPORT_SLUG.
    const req = createAccessRequest(
      {
        requesterName: "Stripe Recruiter Updated",
        requesterEmail: "recruiter@stripe.com",
        company: "Stripe",
        role: "Hiring",
        reason: "Re-submitting",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      DEMO_PASSPORT_SLUG,
    )
    // Should reuse the sample-stripe-001 ID
    expect(req.id).toBe("sample-stripe-001")
    expect(req.status).toBe("pending")
    // Store should have exactly one entry from "recruiter@stripe.com" for DEMO_PASSPORT_SLUG
    const entries = listStudentAccessRequests().filter(
      (r) => r.passportSlug === DEMO_PASSPORT_SLUG && r.requesterEmail === "recruiter@stripe.com",
    )
    expect(entries).toHaveLength(1)
    expect(entries[0].requesterName).toBe("Stripe Recruiter Updated")
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

// ── 6. End-to-end recruiter→student→recruiter flow ────────────────────────────

function makeRecruiterView(slug: string): RecruiterPassportViewResponse {
  return {
    public_slug: slug,
    student_display_name: "Test Candidate",
    field: "AI",
    public_title: "AI Engineer",
    public_summary: "Test summary",
    overall_score: 75,
    evidence_confidence: "medium",
    verification_status: null,
    readiness_level: null,
    skill_groups: [],
    verified_skills: [],
    partially_verified_skills: [],
    skills_needing_review: [],
    proof_sources: [],
    why_credible: [],
    strongest_skills: [],
    areas_needing_review: [],
    suggested_interview_questions: [],
    public_project_links: [],
    project_type: "AI",
    access_request_available: true,
    has_protected_evidence: true,
    disclosure_note: "Test disclosure",
  }
}

describe("End-to-end: recruiter submit → student approve → recruiter reload", () => {
  const TEST_SLUG = "e2e-test-passport-slug"

  beforeEach(() => { clearAccessRequestStore() })

  it("recruiter submit creates a pending request in the mock store", () => {
    const req = createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "E2E Corp",
        role: "Hiring Manager",
        reason: "Integration test",
        requestedEvidenceTypes: ["workflow_recordings", "detailed_skill_evidence"],
        messageToStudent: "Hi from E2E",
      },
      TEST_SLUG,
    )
    expect(req.status).toBe("pending")
    expect(req.passportSlug).toBe(TEST_SLUG)
    const stored = listStudentAccessRequests()
    const found = stored.find((r) => r.id === req.id)
    expect(found).toBeTruthy()
    expect(found?.status).toBe("pending")
  })

  it("student approval updates the stored request to approved", () => {
    const req = createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "E2E Corp",
        role: "Hiring Manager",
        reason: "Integration test",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    const stored = listStudentAccessRequests()
    const updated = stored.find((r) => r.id === req.id)
    expect(updated?.status).toBe("approved")
    expect(updated?.approvedEvidenceTypes).toEqual(["workflow_recordings"])
  })

  it("recruiter preview reads approved request and shows Access approved card", async () => {
    const req = createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(TEST_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-approved-card")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Access approved/i)).toBeInTheDocument()
    expect(screen.getByText(/Protected evidence available/i)).toBeInTheDocument()
    expect(screen.queryByText(/Request Evidence Access/i)).not.toBeInTheDocument()
  })

  it("recruiter preview shows pending card when request is pending", async () => {
    createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(TEST_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Request pending/i)).toBeInTheDocument()
    expect(screen.getByText(/Student approval required/i)).toBeInTheDocument()
  })

  it("recruiter preview shows denied card when request is denied", async () => {
    const req = createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )
    denyAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(TEST_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Access denied/i)).toBeInTheDocument()
  })

  it("recruiter preview shows revoked card when access was revoked", async () => {
    const req = createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    revokeAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(TEST_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-revoked-card")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Access revoked/i)).toBeInTheDocument()
  })

  it("recruiter preview uses most recent request when multiple exist", async () => {
    // Older denied request
    const old = createAccessRequest(
      {
        requesterName: "E2E Recruiter",
        requesterEmail: "e2e@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["workflow_recordings"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )
    denyAccessRequest(old.id)

    // Newer pending request (store prepends, so this will sort as newest)
    createAccessRequest(
      {
        requesterName: "E2E Recruiter 2",
        requesterEmail: "e2e2@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: ["detailed_skill_evidence"],
        messageToStudent: "",
      },
      TEST_SLUG,
    )

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(TEST_SLUG)} />)
    })

    // Newest is pending, not denied
    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
  })
})

// ── 7. Dev reset controls and safe duplicate handling ─────────────────────────

describe("clearMockEvidenceAccessRequests — named export", () => {
  it("is exported and clears the store so sample data is returned on next read", () => {
    createAccessRequest(
      { requesterName: "X", requesterEmail: "x@y.com", company: "", role: "", reason: "", requestedEvidenceTypes: [], messageToStudent: "" },
      "some-slug",
    )
    clearMockEvidenceAccessRequests()
    // After clear, load() falls back to SAMPLE_REQUESTS
    const restored = listStudentAccessRequests()
    expect(restored.some((r) => r.requesterName === "Stripe Early Talent")).toBe(true)
  })

  it("clearMockEvidenceAccessRequests and clearAccessRequestStore produce the same result", () => {
    createAccessRequest(
      { requesterName: "A", requesterEmail: "a@b.com", company: "", role: "", reason: "", requestedEvidenceTypes: [], messageToStudent: "" },
      "slug-a",
    )
    clearMockEvidenceAccessRequests()
    const afterClear = listStudentAccessRequests().map((r) => r.id)

    createAccessRequest(
      { requesterName: "B", requesterEmail: "b@c.com", company: "", role: "", reason: "", requestedEvidenceTypes: [], messageToStudent: "" },
      "slug-b",
    )
    clearAccessRequestStore()
    const afterClearStore = listStudentAccessRequests().map((r) => r.id)

    expect(afterClear).toEqual(afterClearStore)
  })
})

describe("RecruiterWorkPassportPreview — reset and request-again controls", () => {
  const CTRL_SLUG = "ctrl-test-slug"

  beforeEach(() => { clearAccessRequestStore() })

  it("pending card shows reset button when onReset prop is provided", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    const onReset = vi.fn()

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(CTRL_SLUG)}
          onReset={onReset}
        />,
      )
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    const resetBtn = screen.getByTestId("pending-reset-btn")
    expect(resetBtn).toBeInTheDocument()
    expect(resetBtn.textContent).toMatch(/Reset mock access requests/i)
    fireEvent.click(resetBtn)
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it("pending card does NOT show reset button when onReset prop is omitted", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(CTRL_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("pending-reset-btn")).not.toBeInTheDocument()
  })

  it("after clearMockEvidenceAccessRequests, component shows Request Evidence Access CTA (slug not in sample data)", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    clearMockEvidenceAccessRequests()

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(CTRL_SLUG)}
        />,
      )
    })

    // CTRL_SLUG is not in sample data so no request found — CTA shown
    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("access-pending-card")).not.toBeInTheDocument()
  })

  it("denied card shows Send another request button", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    denyAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(CTRL_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("request-again-btn")).toBeInTheDocument()
  })

  it("clicking Send another request on denied card shows Request Evidence Access CTA", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    denyAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(CTRL_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("request-again-btn"))
    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("access-denied-card")).not.toBeInTheDocument()
  })

  it("revoked card shows Send another request button", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    revokeAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(CTRL_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-revoked-card")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("request-again-btn")).toBeInTheDocument()
    // Reset button should NOT appear when onReset is omitted
    expect(screen.queryByTestId("revoked-reset-btn")).not.toBeInTheDocument()
  })

  it("denied card shows dev reset button only when onReset prop is provided", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    denyAccessRequest(req.id)
    const onReset = vi.fn()

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(CTRL_SLUG)}
          onReset={onReset}
        />,
      )
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    const resetBtn = screen.getByTestId("denied-reset-btn")
    expect(resetBtn).toBeInTheDocument()
    fireEvent.click(resetBtn)
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it("approved request is not overridden when recruiter resubmits — stays approved", () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])

    // Attempt resubmit
    const req2 = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["detailed_skill_evidence"], messageToStudent: "" },
      CTRL_SLUG,
    )
    // Should return the existing approved entry unchanged
    expect(req2.id).toBe(req.id)
    expect(req2.status).toBe("approved")
    expect(req2.approvedEvidenceTypes).toEqual(["workflow_recordings"])
    // Only one entry for this recruiter+slug
    const entries = listStudentAccessRequests().filter(
      (r) => r.passportSlug === CTRL_SLUG && r.requesterEmail === "r@co.com",
    )
    expect(entries).toHaveLength(1)
    expect(entries[0].status).toBe("approved")
  })

  it("pending over denied is allowed — resubmit after denial works", () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    denyAccessRequest(req.id)

    // Re-submit after denial — should upsert to pending
    const req2 = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["detailed_skill_evidence"], messageToStudent: "" },
      CTRL_SLUG,
    )
    expect(req2.id).toBe(req.id)
    expect(req2.status).toBe("pending")
    expect(req2.requestedEvidenceTypes).toEqual(["detailed_skill_evidence"])
  })
})
