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
  it("writes an explicit [] so load() returns empty — does NOT fall back to sample data", () => {
    createAccessRequest(
      { requesterName: "X", requesterEmail: "x@y.com", company: "", role: "", reason: "", requestedEvidenceTypes: [], messageToStudent: "" },
      "some-slug",
    )
    clearMockEvidenceAccessRequests()
    // Explicit [] written — no fallback to SAMPLE_REQUESTS
    expect(listStudentAccessRequests()).toHaveLength(0)
  })

  it("differs from clearAccessRequestStore: clearMock prevents sample fallback; clearStore allows it", () => {
    // clearMockEvidenceAccessRequests writes [] → empty, no sample fallback
    clearMockEvidenceAccessRequests()
    expect(listStudentAccessRequests()).toHaveLength(0)

    // clearAccessRequestStore removes the key → load() falls back to SAMPLE_REQUESTS
    clearAccessRequestStore()
    expect(listStudentAccessRequests().length).toBeGreaterThan(0)
    expect(listStudentAccessRequests().some((r) => r.requesterName === "Stripe Early Talent")).toBe(true)
  })

  it("even DEMO_PASSPORT_SLUG requests return empty after clearMockEvidenceAccessRequests", () => {
    createAccessRequest(
      { requesterName: "Stripe", requesterEmail: "recruiter@stripe.com", company: "Stripe", role: "Hiring", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      DEMO_PASSPORT_SLUG,
    )
    clearMockEvidenceAccessRequests()
    const forDemo = listStudentAccessRequests().filter((r) => r.passportSlug === DEMO_PASSPORT_SLUG)
    // No sample fallback — the pending sample-stripe-001 entry is NOT returned
    expect(forDemo).toHaveLength(0)
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

  it("clicking pending-reset-btn immediately shows Request Evidence Access CTA and clears the store", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    // onReset simulates what the dev page does: clear the store
    const onReset = vi.fn(() => { clearMockEvidenceAccessRequests() })

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(CTRL_SLUG)}
          onReset={onReset}
        />,
      )
    })

    // Pending card must be visible first
    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )

    // Click the reset button inside the pending card
    fireEvent.click(screen.getByTestId("pending-reset-btn"))

    // CTA must appear immediately (component clears local state before parent remount)
    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("access-pending-card")).not.toBeInTheDocument()

    // Parent callback was called
    expect(onReset).toHaveBeenCalledTimes(1)

    // Store is truly empty — no sample-data pending will be re-loaded on next mount
    expect(listStudentAccessRequests()).toHaveLength(0)
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

  it("after clearMockEvidenceAccessRequests, component shows Request Evidence Access CTA (store is truly empty, no sample fallback)", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      CTRL_SLUG,
    )
    // clearMockEvidenceAccessRequests writes [] so even slugs in SAMPLE_REQUESTS return null
    clearMockEvidenceAccessRequests()

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(CTRL_SLUG)}
        />,
      )
    })

    // Store is empty — no matching request found — CTA shown
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

// ── 8. Protected evidence unlocked sections ───────────────────────────────────

describe("RecruiterWorkPassportPreview — unlocked evidence sections", () => {
  const UNLOCK_SLUG = "unlock-test-slug"

  beforeEach(() => { clearMockEvidenceAccessRequests() })

  function seedApproved(approvedTypes: string[]) {
    const req = createAccessRequest(
      {
        requesterName: "R",
        requesterEmail: "r@co.com",
        company: "",
        role: "",
        reason: "",
        requestedEvidenceTypes: approvedTypes,
        messageToStudent: "",
      },
      UNLOCK_SLUG,
    )
    approveAccessRequest(req.id, approvedTypes)
  }

  it("shows workflow recordings section when workflow_recordings is approved", async () => {
    seedApproved(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("unlocked-workflow-recordings")).toBeInTheDocument()
    // Count badge shows 3 available (from fallback titles)
    expect(screen.getByText("3 available")).toBeInTheDocument()
    // Fallback recording titles rendered
    expect(screen.getByText(/Browser ML Demo/i)).toBeInTheDocument()
    expect(screen.getByText(/Three\.js WebGL/i)).toBeInTheDocument()
    expect(screen.getByText(/HuggingChat/i)).toBeInTheDocument()
    // Other sections absent
    expect(screen.queryByTestId("unlocked-project-defense")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlocked-detailed-skill-evidence")).not.toBeInTheDocument()
  })

  it("shows project defense summary section when project_defense_media is approved", async () => {
    seedApproved(["project_defense_media"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-project-defense")).toBeInTheDocument(),
    )
    expect(screen.getByText(/Project defense transcript available/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Candidate explained project goal, implementation approach/i),
    ).toBeInTheDocument()
    // Other sections absent
    expect(screen.queryByTestId("unlocked-workflow-recordings")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlocked-detailed-skill-evidence")).not.toBeInTheDocument()
  })

  it("shows skill evidence breakdown section when detailed_skill_evidence is approved", async () => {
    seedApproved(["detailed_skill_evidence"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-detailed-skill-evidence")).toBeInTheDocument(),
    )
    // Fallback skill rows rendered
    expect(screen.getByText("AI / Machine Learning")).toBeInTheDocument()
    expect(screen.getByText("JavaScript / Frontend")).toBeInTheDocument()
    expect(screen.getByText("Data & Visualization")).toBeInTheDocument()
    // Other sections absent
    expect(screen.queryByTestId("unlocked-workflow-recordings")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlocked-project-defense")).not.toBeInTheDocument()
  })

  it("shows all three sections when all three evidence types are approved", async () => {
    seedApproved(["workflow_recordings", "project_defense_media", "detailed_skill_evidence"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("unlocked-workflow-recordings")).toBeInTheDocument()
    expect(screen.getByTestId("unlocked-project-defense")).toBeInTheDocument()
    expect(screen.getByTestId("unlocked-detailed-skill-evidence")).toBeInTheDocument()
    // Section heading and privacy notice
    expect(screen.getByText(/Protected evidence unlocked/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Only evidence types approved by the student are visible/i),
    ).toBeInTheDocument()
  })

  it("uploaded_documents alone renders the unlocked section card with viewer button but no inline sub-sections", async () => {
    seedApproved(["uploaded_documents"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    // Unlocked section card is shown (hasDocs = true)
    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )
    // Evidence viewer button shown (documents are accessible via the viewer)
    expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument()
    // No workflow / defense / skill inline sub-sections
    expect(screen.queryByTestId("unlocked-workflow-recordings")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlocked-project-defense")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlocked-detailed-skill-evidence")).not.toBeInTheDocument()
  })

  it("pending state does not show unlocked evidence section", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      UNLOCK_SLUG,
    )

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("unlocked-evidence-section")).not.toBeInTheDocument()
  })

  it("denied state does not show unlocked evidence section", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      UNLOCK_SLUG,
    )
    denyAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("unlocked-evidence-section")).not.toBeInTheDocument()
  })

  it("revoked state does not show unlocked evidence section", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      UNLOCK_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    revokeAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-revoked-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("unlocked-evidence-section")).not.toBeInTheDocument()
  })

  it("after reset, re-mounted component shows Request Evidence Access CTA (not unlocked section)", async () => {
    seedApproved(["workflow_recordings", "detailed_skill_evidence"])

    const { unmount } = render(
      <RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />,
    )

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )

    // Simulate the banner reset: clear store then unmount+remount (key change in page)
    clearMockEvidenceAccessRequests()
    unmount()

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    // Store is empty for UNLOCK_SLUG → no request → CTA shown
    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("unlocked-evidence-section")).not.toBeInTheDocument()
  })

  it("no private URLs, tokens, or debug metadata in approved unlocked section", async () => {
    seedApproved(["workflow_recordings", "project_defense_media", "detailed_skill_evidence"])

    let container!: HTMLElement
    await act(async () => {
      const result = render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
      container = result.container
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )

    const html = container.innerHTML
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("private_url")
    expect(html).not.toContain("raw_risk")
    expect(html).not.toContain("debug_metadata")
    expect(html).not.toContain("admin_notes")
    // Actual recording titles are label-only, no URL tokens
    expect(html).not.toContain("blob:")
    expect(html).not.toContain("storage.googleapis.com")
  })

  it("uses public_project_links labels as recording titles when provided in the view", async () => {
    seedApproved(["workflow_recordings"])

    const viewWithLinks = {
      ...makeRecruiterView(UNLOCK_SLUG),
      public_project_links: [
        { label: "Custom Project Alpha", url: "https://example.com/alpha" },
        { label: "Custom Project Beta",  url: "https://example.com/beta" },
      ],
    }

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={viewWithLinks} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-workflow-recordings")).toBeInTheDocument(),
    )
    // titles appear both in project-links section and workflow section — at least one match is enough
    expect(screen.getAllByText("Custom Project Alpha").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Custom Project Beta").length).toBeGreaterThan(0)
    // Badge shows count from the provided links
    expect(screen.getByText("2 available")).toBeInTheDocument()
  })

  // ── Reset button in approved state ──────────────────────────────────────────

  it("approved state renders reset button when onReset prop is provided", async () => {
    seedApproved(["workflow_recordings"])
    const onReset = vi.fn(() => { clearMockEvidenceAccessRequests() })

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(UNLOCK_SLUG)}
          onReset={onReset}
        />,
      )
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-approved-card")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("approved-reset-btn")).toBeInTheDocument()
    expect(screen.getByTestId("approved-reset-btn").textContent).toMatch(
      /Reset mock access requests/i,
    )
  })

  it("approved state does NOT render reset button when onReset prop is omitted", async () => {
    seedApproved(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-approved-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("approved-reset-btn")).not.toBeInTheDocument()
  })

  it("clicking reset from approved state immediately hides unlocked evidence and shows Request Evidence Access", async () => {
    seedApproved(["workflow_recordings", "project_defense_media"])
    const onReset = vi.fn(() => { clearMockEvidenceAccessRequests() })

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(UNLOCK_SLUG)}
          onReset={onReset}
        />,
      )
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )
    // Both approved card and unlocked section are visible
    expect(screen.getByTestId("access-approved-card")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("approved-reset-btn"))

    // Component state clears immediately — CTA shown
    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("access-approved-card")).not.toBeInTheDocument()
    expect(screen.queryByTestId("unlocked-evidence-section")).not.toBeInTheDocument()
    expect(onReset).toHaveBeenCalledTimes(1)
    // Store is cleared — no pending sample data will re-load
    expect(listStudentAccessRequests()).toHaveLength(0)
  })

  it("CTA state renders reset button when onReset prop is provided", async () => {
    // No request in store — CTA shown
    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(UNLOCK_SLUG)}
          onReset={vi.fn()}
        />,
      )
    })

    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("cta-reset-btn")).toBeInTheDocument()
  })

  it("CTA state does NOT render reset button when onReset prop is omitted", async () => {
    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("cta-reset-btn")).not.toBeInTheDocument()
  })

  // ── View-detail interaction tests ────────────────────────────────────────────

  it("approved workflow_recordings shows View summary button on each recording card", async () => {
    seedApproved(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-workflow-recordings")).toBeInTheDocument(),
    )
    // Three fallback recording cards each have a View summary button
    const btns = screen.getAllByTestId("view-recording-btn")
    expect(btns.length).toBeGreaterThanOrEqual(1)
    expect(btns[0].textContent).toBe("View summary")
  })

  it("clicking View summary opens recording detail panel with recruiter-safe content", async () => {
    seedApproved(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getAllByTestId("view-recording-btn").length).toBeGreaterThan(0),
    )
    // No panel yet
    expect(screen.queryByTestId("recording-detail-panel")).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByTestId("view-recording-btn")[0])

    // Panel appears
    const panel = screen.getByTestId("recording-detail-panel")
    expect(panel).toBeInTheDocument()
    expect(panel.textContent).toMatch(/Recruiter-safe evidence preview/i)
    expect(panel.textContent).toMatch(/Observed highlights/i)
    expect(panel.textContent).toMatch(/Detailed raw evidence remains controlled by the student/i)
    // Button toggles to "Hide summary"
    expect(screen.getAllByTestId("view-recording-btn")[0].textContent).toBe("Hide summary")
  })

  it("approved project_defense_media shows View transcript summary button", async () => {
    seedApproved(["project_defense_media"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-project-defense")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("view-transcript-btn")).toBeInTheDocument()
    expect(screen.getByTestId("view-transcript-btn").textContent).toBe("View transcript summary")
    // Detail panel is not yet visible
    expect(screen.queryByTestId("defense-detail-panel")).not.toBeInTheDocument()
  })

  it("clicking View transcript summary opens defense detail panel with recruiter-safe content", async () => {
    seedApproved(["project_defense_media"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("view-transcript-btn")).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByTestId("view-transcript-btn"))

    const panel = screen.getByTestId("defense-detail-panel")
    expect(panel).toBeInTheDocument()
    expect(panel.textContent).toMatch(/Recruiter-safe evidence preview/i)
    expect(panel.textContent).toMatch(/Ownership signals/i)
    expect(panel.textContent).toMatch(/Technical depth/i)
    expect(panel.textContent).toMatch(/Limitations noted/i)
    expect(panel.textContent).toMatch(/Detailed raw evidence remains controlled by the student/i)
    expect(screen.getByTestId("view-transcript-btn").textContent).toBe("Hide summary")
  })

  it("approved detailed_skill_evidence shows View evidence button on each skill row", async () => {
    seedApproved(["detailed_skill_evidence"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-detailed-skill-evidence")).toBeInTheDocument(),
    )
    const btns = screen.getAllByTestId("view-skill-evidence-btn")
    expect(btns.length).toBeGreaterThanOrEqual(1)
    expect(btns[0].textContent).toBe("View evidence")
  })

  it("clicking View evidence expands skill detail panel with support and interview question", async () => {
    seedApproved(["detailed_skill_evidence"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getAllByTestId("view-skill-evidence-btn").length).toBeGreaterThan(0),
    )
    // No panels yet
    expect(screen.queryByTestId("skill-detail-panel")).not.toBeInTheDocument()

    fireEvent.click(screen.getAllByTestId("view-skill-evidence-btn")[0])

    const panel = screen.getByTestId("skill-detail-panel")
    expect(panel).toBeInTheDocument()
    expect(panel.textContent).toMatch(/Recruiter-safe evidence preview/i)
    expect(panel.textContent).toMatch(/What supports this claim/i)
    expect(panel.textContent).toMatch(/What needs review/i)
    expect(panel.textContent).toMatch(/Suggested interview question/i)
    expect(panel.textContent).toMatch(/Detailed raw evidence remains controlled by the student/i)
    // Button toggles
    expect(screen.getAllByTestId("view-skill-evidence-btn")[0].textContent).toBe("Hide evidence")
  })

  it("clicking a detail button again collapses the panel", async () => {
    seedApproved(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getAllByTestId("view-recording-btn").length).toBeGreaterThan(0),
    )

    const btn = screen.getAllByTestId("view-recording-btn")[0]
    fireEvent.click(btn)
    expect(screen.getByTestId("recording-detail-panel")).toBeInTheDocument()

    fireEvent.click(btn)
    expect(screen.queryByTestId("recording-detail-panel")).not.toBeInTheDocument()
  })

  it("detail panels do not expose private fields, localhost, tokens, or storage paths", async () => {
    seedApproved(["workflow_recordings", "project_defense_media", "detailed_skill_evidence"])

    let container!: HTMLElement
    await act(async () => {
      const r = render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
      container = r.container
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-evidence-section")).toBeInTheDocument(),
    )

    // Open all detail panels
    for (const btn of screen.getAllByTestId("view-recording-btn")) {
      fireEvent.click(btn)
    }
    fireEvent.click(screen.getByTestId("view-transcript-btn"))
    for (const btn of screen.getAllByTestId("view-skill-evidence-btn")) {
      fireEvent.click(btn)
    }

    const html = container.innerHTML
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("session_id")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("raw_url")
    expect(html).not.toContain("debug_metadata")
    expect(html).not.toContain("admin_notes")
    expect(html).not.toContain("blob:")
    expect(html).not.toContain("transcript_text")
  })

  it("unapproved evidence type does not render its detail buttons", async () => {
    // Only workflow_recordings approved — project_defense and skill_evidence not approved
    seedApproved(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("unlocked-workflow-recordings")).toBeInTheDocument(),
    )
    // Workflow detail buttons present
    expect(screen.getAllByTestId("view-recording-btn").length).toBeGreaterThan(0)
    // No project defense or skill evidence sections
    expect(screen.queryByTestId("view-transcript-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("view-skill-evidence-btn")).not.toBeInTheDocument()
  })

  it("pending state shows no View summary or View evidence buttons", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings", "detailed_skill_evidence"], messageToStudent: "" },
      UNLOCK_SLUG,
    )

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("view-recording-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("view-skill-evidence-btn")).not.toBeInTheDocument()
  })

  it("denied state shows no detail action buttons", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      UNLOCK_SLUG,
    )
    denyAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(UNLOCK_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("view-recording-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("view-transcript-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("view-skill-evidence-btn")).not.toBeInTheDocument()
  })
})

// ── 9. Evidence viewer modal ──────────────────────────────────────────────────

describe("RecruiterWorkPassportPreview — evidence viewer modal", () => {
  const EV_SLUG = "ev-test-slug"

  beforeEach(() => { clearMockEvidenceAccessRequests() })

  function seedApprovedTypes(types: string[]) {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: types, messageToStudent: "" },
      EV_SLUG,
    )
    approveAccessRequest(req.id, types)
  }

  it("approved access shows Open evidence viewer button", async () => {
    seedApprovedTypes(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("open-evidence-viewer-btn").textContent).toBe("Open evidence viewer")
  })

  it("pending state does not show Open evidence viewer button", async () => {
    createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      EV_SLUG,
    )

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-pending-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("open-evidence-viewer-btn")).not.toBeInTheDocument()
  })

  it("denied state does not show Open evidence viewer button", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      EV_SLUG,
    )
    denyAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-denied-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("open-evidence-viewer-btn")).not.toBeInTheDocument()
  })

  it("revoked state does not show Open evidence viewer button", async () => {
    const req = createAccessRequest(
      { requesterName: "R", requesterEmail: "r@co.com", company: "", role: "", reason: "", requestedEvidenceTypes: ["workflow_recordings"], messageToStudent: "" },
      EV_SLUG,
    )
    approveAccessRequest(req.id, ["workflow_recordings"])
    revokeAccessRequest(req.id)

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("access-revoked-card")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("open-evidence-viewer-btn")).not.toBeInTheDocument()
  })

  it("clicking Open evidence viewer shows the modal with Recruiter-safe evidence viewer heading", async () => {
    seedApprovedTypes(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("evidence-viewer-modal")).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    const modal = screen.getByTestId("evidence-viewer-modal")
    expect(modal).toBeInTheDocument()
    expect(modal.textContent).toMatch(/Evidence Viewer/i)
    expect(modal.textContent).toMatch(/Recruiter-safe evidence viewer/i)
    expect(modal.textContent).toMatch(/Only evidence types approved by the student are shown/i)
    expect(modal.textContent).toMatch(/Use this evidence to validate VeriBridge/i)
  })

  it("closing viewer with × button removes the modal", async () => {
    seedApprovedTypes(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))
    expect(screen.getByTestId("evidence-viewer-modal")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("close-evidence-viewer-btn"))
    expect(screen.queryByTestId("evidence-viewer-modal")).not.toBeInTheDocument()
  })

  it("workflow recordings tab appears when workflow_recordings is approved", async () => {
    seedApprovedTypes(["workflow_recordings"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    await waitFor(() =>
      expect(screen.getByTestId("viewer-workflow-tab")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("viewer-workflow-tab").textContent).toMatch(/Keyframe/i)
    // Tab button only appears when multiple tabs; single tab renders content directly
    // No project defense or documents tab button
    expect(screen.queryByTestId("evidence-tab-project_defense_media")).not.toBeInTheDocument()
    expect(screen.queryByTestId("evidence-tab-uploaded_documents")).not.toBeInTheDocument()
  })

  it("project defense tab appears only when project_defense_media is approved", async () => {
    seedApprovedTypes(["project_defense_media"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    await waitFor(() =>
      expect(screen.getByTestId("viewer-defense-tab")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("viewer-defense-tab").textContent).toMatch(/Transcript excerpt/i)
    expect(screen.getByTestId("viewer-defense-tab").textContent).toMatch(/Ownership signals/i)
    expect(screen.queryByTestId("viewer-workflow-tab")).not.toBeInTheDocument()
  })

  it("skill evidence tab appears only when detailed_skill_evidence is approved", async () => {
    seedApprovedTypes(["detailed_skill_evidence"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    await waitFor(() =>
      expect(screen.getByTestId("viewer-skill-tab")).toBeInTheDocument(),
    )
    // Source drill-down shown
    expect(screen.getByTestId("viewer-skill-tab").textContent).toMatch(/Evidence source breakdown/i)
    expect(screen.getByTestId("viewer-skill-tab").textContent).toMatch(/Supported/i)
    expect(screen.queryByTestId("viewer-workflow-tab")).not.toBeInTheDocument()
  })

  it("documents tab appears only when uploaded_documents is approved", async () => {
    seedApprovedTypes(["uploaded_documents"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    await waitFor(() =>
      expect(screen.getByTestId("viewer-documents-tab")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("viewer-documents-tab").textContent).toMatch(/Document summary/i)
    expect(screen.getByTestId("viewer-documents-tab").textContent).toMatch(/AI Engineering Project Report/i)
    expect(screen.getByTestId("viewer-documents-tab").textContent).toMatch(/Raw document file is not exposed/i)
    expect(screen.queryByTestId("viewer-workflow-tab")).not.toBeInTheDocument()
  })

  it("all four tabs appear when all four types are approved", async () => {
    seedApprovedTypes([
      "workflow_recordings", "project_defense_media",
      "detailed_skill_evidence", "uploaded_documents",
    ])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    await waitFor(() =>
      expect(screen.getByTestId("evidence-viewer-modal")).toBeInTheDocument(),
    )
    expect(screen.getByTestId("evidence-tab-workflow_recordings")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-tab-project_defense_media")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-tab-detailed_skill_evidence")).toBeInTheDocument()
    expect(screen.getByTestId("evidence-tab-uploaded_documents")).toBeInTheDocument()
  })

  it("clicking a tab in the viewer switches content", async () => {
    seedApprovedTypes(["workflow_recordings", "project_defense_media"])

    await act(async () => {
      render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    // Workflow is default active tab
    await waitFor(() =>
      expect(screen.getByTestId("viewer-workflow-tab")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("viewer-defense-tab")).not.toBeInTheDocument()

    // Switch to project defense tab
    fireEvent.click(screen.getByTestId("evidence-tab-project_defense_media"))
    expect(screen.getByTestId("viewer-defense-tab")).toBeInTheDocument()
    expect(screen.queryByTestId("viewer-workflow-tab")).not.toBeInTheDocument()
  })

  it("viewer does not render unsafe private strings when all tabs are open", async () => {
    seedApprovedTypes([
      "workflow_recordings", "project_defense_media",
      "detailed_skill_evidence", "uploaded_documents",
    ])

    let container!: HTMLElement
    await act(async () => {
      const r = render(<RecruiterWorkPassportPreview view={makeRecruiterView(EV_SLUG)} />)
      container = r.container
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId("open-evidence-viewer-btn"))

    await waitFor(() =>
      expect(screen.getByTestId("evidence-viewer-modal")).toBeInTheDocument(),
    )

    // Check all tabs
    const tabs = [
      "evidence-tab-workflow_recordings",
      "evidence-tab-project_defense_media",
      "evidence-tab-detailed_skill_evidence",
      "evidence-tab-uploaded_documents",
    ]
    for (const tabId of tabs) {
      const tabBtn = screen.queryByTestId(tabId)
      if (tabBtn) fireEvent.click(tabBtn)
    }

    const html = container.innerHTML
    expect(html).not.toContain("localhost")
    expect(html).not.toContain("127.0.0.1")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("session_id")
    expect(html).not.toContain("storage_path")
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("raw_url")
    expect(html).not.toContain("debug_metadata")
    expect(html).not.toContain("admin_notes")
    expect(html).not.toContain("blob:")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("supabase")
    expect(html).not.toContain("private_url")
  })

  it("reset mock access requests hides evidence viewer button", async () => {
    seedApprovedTypes(["workflow_recordings"])
    const onReset = vi.fn(() => { clearMockEvidenceAccessRequests() })

    await act(async () => {
      render(
        <RecruiterWorkPassportPreview
          view={makeRecruiterView(EV_SLUG)}
          onReset={onReset}
        />,
      )
    })

    await waitFor(() =>
      expect(screen.getByTestId("open-evidence-viewer-btn")).toBeInTheDocument(),
    )

    // Reset via the approved card reset button
    fireEvent.click(screen.getByTestId("approved-reset-btn"))

    // After reset, approved state is cleared → unlocked section removed → button gone
    await waitFor(() =>
      expect(screen.getByTestId("request-access-btn")).toBeInTheDocument(),
    )
    expect(screen.queryByTestId("open-evidence-viewer-btn")).not.toBeInTheDocument()
    expect(screen.queryByTestId("evidence-viewer-modal")).not.toBeInTheDocument()
  })
})
