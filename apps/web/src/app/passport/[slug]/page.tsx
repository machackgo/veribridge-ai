"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import {
  getPublicPassport,
  getPublicWorkPassportStatus,
  getPublicSkillEvidenceTimeline,
  getPublicGitHubProofs,
  requestPassportAccess,
  savePublicPassport,
  type PublicPassportSafeResponse,
  type PublicWorkPassportStatusResponse,
  type SkillEvidenceTimelineResponse,
  type GitHubProofPublicResponse,
  type AccessRequestCreate,
} from "@/lib/passport-api"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  ProgressBar,
  SupportLevelBadge,
  TOKEN,
} from "../../../../components/passport/shared"

// ── Request Access Modal ──────────────────────────────────────────────────────

const DEFAULT_SECTIONS = ["workflow", "github", "project_defense", "ai_domain_review"]

function RequestAccessForm({
  publicSlug,
  onSubmitted,
  onCancel,
}: {
  publicSlug: string
  onSubmitted: () => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<AccessRequestCreate>({
    requester_name: "",
    requester_email: "",
    requester_organization: "",
    requester_role: "",
    request_reason: "",
    requested_sections: DEFAULT_SECTIONS,
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSubmit = async () => {
    if (!form.requester_name.trim() || !form.requester_email.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await requestPassportAccess(publicSlug, form)
      setSuccess(true)
      setTimeout(onSubmitted, 1800)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Request failed")
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <div style={{ textAlign: "center", padding: "24px" }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
        <p style={{ fontWeight: 700, fontSize: 16, color: TOKEN.emerald, marginBottom: 4 }}>
          Request submitted
        </p>
        <p style={{ fontSize: 13, color: TOKEN.muted }}>
          The student has been notified. You'll receive an email when they respond.
        </p>
      </div>
    )
  }

  const field = (key: keyof AccessRequestCreate, label: string, placeholder: string, required = false) => (
    <div>
      <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
        {label}{required && " *"}
      </label>
      <input
        type="text"
        placeholder={placeholder}
        value={String(form[key] ?? "")}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
        style={{
          width: "100%",
          padding: "9px 12px",
          border: `1px solid ${TOKEN.line}`,
          borderRadius: 8,
          fontSize: 13,
          background: TOKEN.paper,
          boxSizing: "border-box",
        }}
      />
    </div>
  )

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {field("requester_name", "Full Name", "Jane Smith", true)}
        {field("requester_email", "Work Email", "jane@company.com", true)}
        {field("requester_organization", "Organization", "Acme Corp")}
        {field("requester_role", "Your Role", "Engineering Recruiter")}
      </div>
      <div>
        <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
          Reason for Access
        </label>
        <textarea
          placeholder="Briefly explain why you're requesting access to this student's evidence…"
          value={form.request_reason ?? ""}
          onChange={(e) => setForm((f) => ({ ...f, request_reason: e.target.value }))}
          rows={3}
          style={{
            width: "100%",
            padding: "9px 12px",
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 8,
            fontSize: 13,
            resize: "vertical",
            boxSizing: "border-box",
          }}
        />
      </div>

      <div
        style={{
          padding: "10px 12px",
          background: TOKEN.indigoSoft,
          borderRadius: 8,
          border: `1px solid #c7d2fe`,
        }}
      >
        <p style={{ fontSize: 12, color: TOKEN.indigo, margin: 0 }}>
          🛡 <strong>Student controls access.</strong> Your request will be sent directly to the student. They must approve before you can view any protected evidence.
        </p>
      </div>

      {error && (
        <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6 }}>
          {error}
        </p>
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Btn variant="secondary" onClick={onCancel}>Cancel</Btn>
        <Btn
          variant="primary"
          onClick={handleSubmit}
          disabled={submitting || !form.requester_name.trim() || !form.requester_email.trim()}
        >
          {submitting ? "Submitting…" : "Request Access"}
        </Btn>
      </div>
    </div>
  )
}

// ── Save Candidate Form ──────────────────────────────────────────────────────

function SaveCandidateForm({
  publicSlug,
  onDone,
}: {
  publicSlug: string
  onDone: () => void
}) {
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [org, setOrg] = useState("")
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async () => {
    if (!email.trim()) return
    setSaving(true)
    setError(null)
    try {
      await savePublicPassport(publicSlug, {
        requester_email: email.trim(),
        requester_name: name.trim() || null,
        organization_name: org.trim() || null,
        status: "saved",
      })
      setSaved(true)
      setTimeout(onDone, 1500)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed")
    } finally {
      setSaving(false)
    }
  }

  if (saved) {
    return (
      <div style={{ textAlign: "center", padding: "16px" }}>
        <div style={{ fontSize: 28, marginBottom: 6 }}>📌</div>
        <p style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>Candidate saved to your shortlist.</p>
      </div>
    )
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div>
          <label style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted, display: "block", marginBottom: 3 }}>Your Email *</label>
          <input
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{ width: "100%", padding: "8px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12, boxSizing: "border-box" }}
          />
        </div>
        <div>
          <label style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted, display: "block", marginBottom: 3 }}>Your Name</label>
          <input
            type="text"
            placeholder="Jane Smith"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: "100%", padding: "8px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12, boxSizing: "border-box" }}
          />
        </div>
      </div>
      <div>
        <label style={{ fontSize: 11, fontWeight: 600, color: TOKEN.muted, display: "block", marginBottom: 3 }}>Organization</label>
        <input
          type="text"
          placeholder="Acme Corp"
          value={org}
          onChange={(e) => setOrg(e.target.value)}
          style={{ width: "100%", padding: "8px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12, boxSizing: "border-box" }}
        />
      </div>
      {error && <p style={{ fontSize: 11, color: TOKEN.rose }}>{error}</p>}
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <Btn size="sm" variant="secondary" onClick={onDone}>Cancel</Btn>
        <Btn size="sm" variant="primary" onClick={handleSave} disabled={saving || !email.trim()}>
          {saving ? "Saving…" : "Save to shortlist"}
        </Btn>
      </div>
    </div>
  )
}

// ── Main Public Passport Page ─────────────────────────────────────────────────

export default function PublicPassportPage() {
  const params = useParams()
  const slug = typeof params.slug === "string" ? params.slug : Array.isArray(params.slug) ? params.slug[0] : ""

  const [passport, setPassport] = useState<PublicPassportSafeResponse | null>(null)
  const [status, setStatus] = useState<PublicWorkPassportStatusResponse | null>(null)
  const [timeline, setTimeline] = useState<SkillEvidenceTimelineResponse | null>(null)
  const [githubProofs, setGithubProofs] = useState<GitHubProofPublicResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAccessForm, setShowAccessForm] = useState(false)
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [accessRequested, setAccessRequested] = useState(false)

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    setError(null)
    Promise.all([
      getPublicPassport(slug),
      getPublicWorkPassportStatus(slug).catch(() => null),
      getPublicSkillEvidenceTimeline(slug).catch(() => null),
      getPublicGitHubProofs(slug).catch(() => []),
    ])
      .then(([p, s, t, gh]) => {
        setPassport(p)
        setStatus(s)
        setTimeline(t)
        setGithubProofs(gh)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [slug])

  if (!slug) return <ErrorState message="Invalid passport URL." />
  if (loading) return <div style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}><LoadingState label="Loading Work Passport…" /></div>
  if (error) return <div style={{ maxWidth: 600, margin: "80px auto" }}><ErrorState message={error} /></div>
  if (!passport) return <EmptyState icon="🪪" title="Passport not found" description="This Work Passport may not exist or is not publicly available." />

  const readiness = passport.readiness_score ?? 0
  const readinessColor = readiness >= 80 ? TOKEN.emerald : readiness >= 50 ? TOKEN.amber : TOKEN.rose

  return (
    <div
      style={{
        minHeight: "100vh",
        background: TOKEN.bg,
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      }}
    >
      {/* Header bar */}
      <div
        style={{
          background: "#0a0e1a",
          padding: "14px 24px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div style={{ width: 28, height: 28, borderRadius: 7, background: "linear-gradient(135deg,#4f46e5,#8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <span style={{ color: "#fff", fontSize: 14, fontWeight: 800 }}>V</span>
        </div>
        <span style={{ color: "#fff", fontWeight: 700, fontSize: 14 }}>VeriBridge AI</span>
        <span style={{ color: "#475569", fontSize: 13 }}>Verified Work Passport</span>
      </div>

      {/* Hero */}
      <div
        style={{
          background: "linear-gradient(135deg, #0a0e1a 0%, #1e293b 100%)",
          padding: "48px 24px 40px",
        }}
      >
        <div style={{ maxWidth: 820, margin: "0 auto" }}>
          <Mono style={{ fontSize: 10, letterSpacing: "0.18em", color: "#64748b", textTransform: "uppercase", display: "block", marginBottom: 8 }}>
            Verified Work Passport
          </Mono>
          <h1 style={{ fontSize: 32, fontWeight: 800, color: "#fff", margin: "0 0 8px", letterSpacing: "-0.03em" }}>
            {passport.public_title ?? passport.student_display_name ?? "Work Passport"}
          </h1>
          {passport.field && (
            <p style={{ fontSize: 14, color: "#94a3b8", margin: "0 0 16px" }}>
              Field: {passport.field}
            </p>
          )}
          {passport.public_summary && (
            <p style={{ fontSize: 15, color: "#cbd5e1", margin: "0 0 24px", lineHeight: 1.6, maxWidth: 600 }}>
              {passport.public_summary}
            </p>
          )}

          {/* Key badges */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 24 }}>
            {status && (
              <Badge
                tone="slate"
                style={{ background: "#1e293b", border: "1px solid #334155", color: "#94a3b8", padding: "5px 12px" }}
              >
                {status.status_label}
              </Badge>
            )}
            {passport.ai_domain_review_status && (
              <Badge
                tone="indigo"
                style={{ padding: "5px 12px" }}
              >
                🤖 AI Reviewed
              </Badge>
            )}
            {passport.readiness_level && (
              <Badge
                tone="emerald"
                style={{ padding: "5px 12px" }}
              >
                Readiness: {passport.readiness_level}
              </Badge>
            )}
          </div>

          {/* Readiness bar */}
          {readiness > 0 && (
            <div style={{ maxWidth: 360, marginBottom: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Mono style={{ fontSize: 10, color: "#64748b", textTransform: "uppercase" }}>Readiness Score</Mono>
                <Mono style={{ fontSize: 13, fontWeight: 700, color: readinessColor }}>{readiness}</Mono>
              </div>
              <ProgressBar value={readiness} color={readinessColor} height={8} />
            </div>
          )}

          {/* CTA buttons */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {passport.access_request_available && !accessRequested && (
              <Btn
                variant="primary"
                onClick={() => setShowAccessForm(true)}
                style={{ background: TOKEN.indigo, padding: "10px 20px" }}
              >
                🔑 Request Evidence Access
              </Btn>
            )}
            {accessRequested && (
              <Badge tone="emerald" style={{ padding: "10px 16px", fontSize: 13 }}>
                ✅ Access request submitted
              </Badge>
            )}
            <Btn
              variant="secondary"
              onClick={() => setShowSaveForm(true)}
              style={{ background: "transparent", border: "1px solid #334155", color: "#94a3b8" }}
            >
              📌 Save candidate
            </Btn>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div style={{ maxWidth: 820, margin: "0 auto", padding: "32px 24px" }}>
        {/* Access request form */}
        {showAccessForm && (
          <Card style={{ marginBottom: 24, border: `1px solid ${TOKEN.indigo}40` }}>
            <CardHeader title="Request Access to Protected Evidence" icon="🔑" />
            <RequestAccessForm
              publicSlug={slug}
              onSubmitted={() => {
                setShowAccessForm(false)
                setAccessRequested(true)
              }}
              onCancel={() => setShowAccessForm(false)}
            />
          </Card>
        )}

        {/* Save form */}
        {showSaveForm && (
          <Card style={{ marginBottom: 24, border: `1px solid ${TOKEN.sky}40` }}>
            <CardHeader title="Save to Your Shortlist" icon="📌" />
            <SaveCandidateForm publicSlug={slug} onDone={() => setShowSaveForm(false)} />
          </Card>
        )}

        {/* Skills summary */}
        {(passport.verified_skills.length > 0 || passport.partially_verified_skills.length > 0) && (
          <Card style={{ marginBottom: 20 }}>
            <CardHeader title="Verified Skills" eyebrow="AI-analyzed evidence" icon="🧠" />
            {passport.verified_skills.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <Mono style={{ fontSize: 10, color: TOKEN.emerald, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Strong</Mono>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {passport.verified_skills.map((s) => <Badge key={s} tone="emerald">{s}</Badge>)}
                </div>
              </div>
            )}
            {passport.partially_verified_skills.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <Mono style={{ fontSize: 10, color: TOKEN.amber, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Partial</Mono>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {passport.partially_verified_skills.map((s) => <Badge key={s} tone="amber">{s}</Badge>)}
                </div>
              </div>
            )}
            {passport.skills_needing_more_evidence.length > 0 && (
              <div>
                <Mono style={{ fontSize: 10, color: TOKEN.rose, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Needs more evidence</Mono>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {passport.skills_needing_more_evidence.map((s) => <Badge key={s} tone="rose">{s}</Badge>)}
                </div>
              </div>
            )}
          </Card>
        )}

        {/* Skill evidence timeline (public-safe) */}
        {timeline && timeline.skills.length > 0 && (
          <Card style={{ marginBottom: 20 }}>
            <CardHeader title="Skill Evidence Timeline" eyebrow="Public summary" icon="📊" />
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {timeline.skills.filter((s) => s.public_safe).map((skill) => (
                <div
                  key={skill.normalized_skill_name}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 12px",
                    background: TOKEN.bg,
                    border: `1px solid ${TOKEN.line}`,
                    borderRadius: 8,
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span style={{ fontWeight: 600, fontSize: 13, color: TOKEN.ink }}>{skill.skill_name}</span>
                      <SupportLevelBadge level={skill.support_level} />
                    </div>
                    <ProgressBar
                      value={skill.confidence_score}
                      color={skill.support_level === "strong" ? TOKEN.emerald : skill.support_level === "partial" ? TOKEN.amber : TOKEN.rose}
                      height={4}
                    />
                  </div>
                  <Mono style={{ fontSize: 11, color: TOKEN.muted, flexShrink: 0 }}>
                    {skill.confidence_score}%
                  </Mono>
                </div>
              ))}
              {timeline.skills.some((s) => !s.public_safe) && (
                <div
                  style={{
                    padding: "10px 12px",
                    background: TOKEN.indigoSoft,
                    border: `1px solid #c7d2fe`,
                    borderRadius: 8,
                    textAlign: "center",
                  }}
                >
                  <p style={{ fontSize: 12, color: TOKEN.indigo, margin: 0 }}>
                    🔒 {timeline.skills.filter((s) => !s.public_safe).length} additional skill(s) in protected evidence — request access to view.
                  </p>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* GitHub proofs (public-safe) */}
        {githubProofs.length > 0 && (
          <Card style={{ marginBottom: 20 }}>
            <CardHeader title="GitHub Repository Evidence" eyebrow="Public repos" icon="🐙" />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {githubProofs.map((proof) => (
                <div
                  key={proof.id}
                  style={{
                    padding: "10px 12px",
                    background: TOKEN.bg,
                    border: `1px solid ${TOKEN.line}`,
                    borderRadius: 8,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <a
                      href={proof.repo_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontWeight: 600, fontSize: 13, color: TOKEN.indigo }}
                    >
                      {proof.repo_owner}/{proof.repo_name}
                    </a>
                    {proof.evidence_strength && (
                      <Badge tone={proof.evidence_strength === "strong" || proof.evidence_strength === "substantial" ? "emerald" : "amber"}>
                        {proof.evidence_strength}
                      </Badge>
                    )}
                  </div>
                  {proof.public_safe_summary && (
                    <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 6px" }}>{proof.public_safe_summary}</p>
                  )}
                  {proof.detected_skills.length > 0 && (
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {proof.detected_skills.map((s) => <Badge key={s} tone="sky">{s}</Badge>)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* AI reviewer info */}
        {passport.ai_domain_reviewer_name && (
          <Card style={{ marginBottom: 20 }}>
            <CardHeader title="AI Domain Review" eyebrow="Automated analysis" icon="🤖" />
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <div
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  background: TOKEN.indigoSoft,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 20,
                  flexShrink: 0,
                }}
              >
                🤖
              </div>
              <div>
                <p style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink, margin: "0 0 2px" }}>
                  {passport.ai_domain_reviewer_name}
                </p>
                <Badge tone="indigo">{passport.ai_domain_review_status ?? "reviewed"}</Badge>
                {passport.ai_domain_review_summary && (
                  <p style={{ fontSize: 12, color: TOKEN.muted, margin: "8px 0 0", lineHeight: 1.5 }}>
                    {passport.ai_domain_review_summary}
                  </p>
                )}
                <p style={{ fontSize: 11, color: TOKEN.muted, margin: "6px 0 0", fontStyle: "italic" }}>
                  This is an AI-generated domain review — not a human or faculty verification.
                </p>
              </div>
            </div>
          </Card>
        )}

        {/* Protected evidence notice */}
        {!accessRequested && passport.access_request_available && (
          <Card
            style={{
              background: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
              border: "none",
              marginBottom: 20,
            }}
          >
            <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
              <span style={{ fontSize: 36 }}>🔒</span>
              <div style={{ flex: 1 }}>
                <p style={{ fontWeight: 700, fontSize: 15, color: "#fff", margin: "0 0 4px" }}>
                  Protected Evidence Available
                </p>
                <p style={{ fontSize: 13, color: "#a5b4fc", margin: "0 0 12px", lineHeight: 1.5 }}>
                  This student has additional verified evidence available on request. Workflow analysis, project defense recordings, and full skill reports require access approval.
                </p>
                <Btn
                  variant="primary"
                  onClick={() => setShowAccessForm(true)}
                  style={{ background: TOKEN.indigo, padding: "8px 18px" }}
                >
                  Request access
                </Btn>
              </div>
            </div>
          </Card>
        )}

        {/* Disclosure note */}
        <div
          style={{
            padding: "12px 14px",
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.6 }}>
            <strong>Disclosure:</strong> {passport.disclosure_note}
          </p>
        </div>

        {/* Footer */}
        <div style={{ textAlign: "center", padding: "8px 0 24px" }}>
          <Mono style={{ fontSize: 10, color: TOKEN.muted }}>
            Verified by VeriBridge AI · Field-aware evidence-based verification
          </Mono>
        </div>
      </div>
    </div>
  )
}
