import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { StudentAccessRequestsPanel } from "../../components/passport/StudentAccessRequestsPanel"
import type { StudentAccessRequest } from "../../components/passport/StudentAccessRequestsPanel"

// ── Fixture helpers ───────────────────────────────────────────────────────────

function makePending(overrides?: Partial<StudentAccessRequest>): StudentAccessRequest {
  return {
    id: "req-001",
    requester_name: "Stripe Early Talent",
    requester_email: "recruiter@stripe.com",
    requester_organization: "Stripe",
    requester_role: "Early Talent / AI Intern Hiring",
    requested_sections: ["workflow_recordings", "project_defense", "detailed_skill_evidence"],
    request_reason: "Reviewing for an AI internship role.",
    status: "pending",
    requested_at: "2026-05-28T10:30:00Z",
    ...overrides,
  }
}

function makeApproved(overrides?: Partial<StudentAccessRequest>): StudentAccessRequest {
  return {
    id: "req-002",
    requester_name: "WPI Faculty",
    requester_email: "faculty@wpi.edu",
    requester_organization: "WPI",
    requester_role: "Faculty Reviewer",
    requested_sections: ["documents", "detailed_skill_evidence"],
    status: "approved",
    requested_at: "2026-05-20T14:00:00Z",
    ...overrides,
  }
}

function makeDenied(overrides?: Partial<StudentAccessRequest>): StudentAccessRequest {
  return {
    id: "req-003",
    requester_name: "Acme Corp",
    requester_email: "recruiter@acme.com",
    requested_sections: ["workflow_recordings"],
    status: "denied",
    requested_at: "2026-05-15T09:00:00Z",
    ...overrides,
  }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("StudentAccessRequestsPanel", () => {
  it("renders title-level privacy callout", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    const callout = screen.getByTestId("privacy-callout")
    expect(callout).toBeInTheDocument()
    expect(callout.textContent).toMatch(/You control who sees your protected evidence/i)
    expect(callout.textContent).toMatch(/Public skill summaries remain visible/i)
    expect(callout.textContent).toMatch(/protected recordings, raw transcripts/i)
  })

  it("renders pending request with Approve and Deny buttons", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    expect(screen.getByTestId("approve-btn-req-001")).toBeInTheDocument()
    expect(screen.getByTestId("deny-btn-req-001")).toBeInTheDocument()
    expect(screen.getByText("Stripe Early Talent")).toBeInTheDocument()
  })

  it("renders approved request with Revoke button (no Approve/Deny)", () => {
    render(<StudentAccessRequestsPanel requests={[makeApproved()]} />)
    expect(screen.getByTestId("revoke-btn-req-002")).toBeInTheDocument()
    expect(screen.queryByTestId("approve-btn-req-002")).not.toBeInTheDocument()
    expect(screen.queryByTestId("deny-btn-req-002")).not.toBeInTheDocument()
  })

  it("denied request shows no action buttons", () => {
    render(<StudentAccessRequestsPanel requests={[makeDenied()]} />)
    expect(screen.queryByTestId("approve-btn-req-003")).not.toBeInTheDocument()
    expect(screen.queryByTestId("deny-btn-req-003")).not.toBeInTheDocument()
    expect(screen.queryByTestId("revoke-btn-req-003")).not.toBeInTheDocument()
    expect(screen.getByText("Acme Corp")).toBeInTheDocument()
  })

  it("clicking Approve opens confirmation modal", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    fireEvent.click(screen.getByTestId("approve-btn-req-001"))
    expect(screen.getByTestId("confirm-modal-approve")).toBeInTheDocument()
    expect(screen.getByText(/Approve protected evidence access/i)).toBeInTheDocument()
  })

  it("approval modal shows section checkboxes with requested sections", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    fireEvent.click(screen.getByTestId("approve-btn-req-001"))
    const modal = screen.getByTestId("confirm-modal-approve")
    expect(modal.textContent).toMatch(/Workflow recordings/i)
    expect(modal.textContent).toMatch(/Project defense/i)
    expect(modal.textContent).toMatch(/Detailed skill evidence/i)
  })

  it("confirming approval changes request status to approved", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    fireEvent.click(screen.getByTestId("approve-btn-req-001"))
    // Sections are pre-checked — confirm button should be enabled
    fireEvent.click(screen.getByText("Approve selected access"))
    // Modal closes; pending request is now approved (Revoke button appears)
    expect(screen.queryByTestId("confirm-modal-approve")).not.toBeInTheDocument()
    expect(screen.getByTestId("revoke-btn-req-001")).toBeInTheDocument()
  })

  it("clicking Deny opens confirmation modal", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    fireEvent.click(screen.getByTestId("deny-btn-req-001"))
    expect(screen.getByTestId("confirm-modal-deny")).toBeInTheDocument()
    expect(screen.getByText(/Deny access request/i)).toBeInTheDocument()
  })

  it("confirming Deny changes status to denied", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    fireEvent.click(screen.getByTestId("deny-btn-req-001"))
    // "Deny request" is the modal confirm button label
    fireEvent.click(screen.getByText("Deny request"))
    expect(screen.queryByTestId("confirm-modal-deny")).not.toBeInTheDocument()
    expect(screen.queryByTestId("approve-btn-req-001")).not.toBeInTheDocument()
    expect(screen.queryByTestId("deny-btn-req-001")).not.toBeInTheDocument()
  })

  it("clicking Revoke opens confirmation modal", () => {
    render(<StudentAccessRequestsPanel requests={[makeApproved()]} />)
    fireEvent.click(screen.getByTestId("revoke-btn-req-002"))
    expect(screen.getByTestId("confirm-modal-revoke")).toBeInTheDocument()
    // Modal header
    expect(screen.getAllByText(/Revoke access/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/no longer be able to view/i)).toBeInTheDocument()
  })

  it("confirming Revoke changes status to revoked", () => {
    render(<StudentAccessRequestsPanel requests={[makeApproved()]} />)
    fireEvent.click(screen.getByTestId("revoke-btn-req-002"))
    // "Revoke access" is the modal confirm button label
    fireEvent.click(screen.getByText("Revoke access"))
    expect(screen.queryByTestId("confirm-modal-revoke")).not.toBeInTheDocument()
    expect(screen.queryByTestId("revoke-btn-req-002")).not.toBeInTheDocument()
  })

  it("Cancel closes the modal without changing state", () => {
    render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    fireEvent.click(screen.getByTestId("approve-btn-req-001"))
    expect(screen.getByTestId("confirm-modal-approve")).toBeInTheDocument()
    fireEvent.click(screen.getByText("Cancel"))
    expect(screen.queryByTestId("confirm-modal-approve")).not.toBeInTheDocument()
    // Still pending — Approve button still present
    expect(screen.getByTestId("approve-btn-req-001")).toBeInTheDocument()
  })

  it("renders with empty requests list gracefully", () => {
    render(<StudentAccessRequestsPanel requests={[]} />)
    expect(screen.getByText(/No access requests yet/i)).toBeInTheDocument()
  })

  it("uses built-in mock data when no requests prop provided", () => {
    render(<StudentAccessRequestsPanel />)
    expect(screen.getByText("Stripe Early Talent")).toBeInTheDocument()
    expect(screen.getByText("WPI Faculty Reviewer")).toBeInTheDocument()
    expect(screen.getByText("Acme Robotics")).toBeInTheDocument()
  })

  it("does not render private field names in UI", () => {
    const { container } = render(<StudentAccessRequestsPanel requests={[makePending()]} />)
    const html = container.innerHTML
    expect(html).not.toContain("media_storage_path")
    expect(html).not.toContain("access_token")
    expect(html).not.toContain("transcript_text")
    expect(html).not.toContain("raw_risk")
    expect(html).not.toContain("debug_metadata")
    expect(html).not.toContain("admin_notes")
  })
})
