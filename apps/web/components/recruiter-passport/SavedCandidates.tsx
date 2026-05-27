"use client"

import { useState } from "react"
import {
  listRecruiterSavedPassports,
  updateRecruiterSavedPassport,
  deleteRecruiterSavedPassport,
  type RecruiterSavedPassportResponse,
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
  ProgressBar,
  StatusBadge,
  TOKEN,
} from "../passport/shared"
import Link from "next/link"

const SAVED_STATUS_OPTIONS = ["saved", "shortlisted", "reviewing", "contacted", "rejected", "archived"]

function CandidateCard({
  saved,
  onUpdate,
  onDelete,
}: {
  saved: RecruiterSavedPassportResponse
  onUpdate: (id: string, update: Partial<RecruiterSavedPassportResponse>) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [notes, setNotes] = useState(saved.private_notes ?? "")
  const [status, setStatus] = useState(saved.status)
  const [fitScore, setFitScore] = useState(saved.fit_score ?? 0)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateRecruiterSavedPassport(saved.id, {
        requester_email: saved.requester_email,
        status: status as "saved",
        private_notes: notes,
        fit_score: fitScore || null,
      })
      onUpdate(saved.id, { private_notes: notes, status: status as "saved", fit_score: fitScore || null })
      setEditing(false)
    } catch {}
    setSaving(false)
  }

  const handleDelete = async () => {
    if (!confirm("Remove this candidate from your shortlist?")) return
    try {
      await deleteRecruiterSavedPassport(saved.id, saved.requester_email)
      onDelete(saved.id)
    } catch {}
  }

  const statusToneMap: Record<string, "emerald" | "amber" | "sky" | "rose" | "slate" | "indigo"> = {
    saved: "slate",
    shortlisted: "indigo",
    reviewing: "amber",
    contacted: "sky",
    rejected: "rose",
    archived: "slate",
  }

  return (
    <Card style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            background: "linear-gradient(135deg,#4f46e5,#8b5cf6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontWeight: 800,
            fontSize: 16,
            flexShrink: 0,
          }}
        >
          {(saved.public_title ?? saved.field ?? "?")[0].toUpperCase()}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>
              {saved.public_title ?? "Work Passport"}
            </span>
            <Badge tone={statusToneMap[saved.status] ?? "slate"}>{saved.status}</Badge>
            {saved.field && <Badge tone="sky">{saved.field}</Badge>}
          </div>

          {saved.public_summary && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 8px", lineHeight: 1.4 }}>
              {saved.public_summary}
            </p>
          )}

          {/* Fit score */}
          {saved.fit_score != null && saved.fit_score > 0 && (
            <div style={{ marginBottom: 8, maxWidth: 240 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase" }}>Match Signal</Mono>
                <Mono style={{ fontSize: 10, color: TOKEN.indigo, fontWeight: 700 }}>{saved.fit_score}%</Mono>
              </div>
              <ProgressBar
                value={saved.fit_score}
                color={saved.fit_score >= 70 ? TOKEN.emerald : saved.fit_score >= 40 ? TOKEN.amber : TOKEN.rose}
                height={5}
              />
            </div>
          )}

          {/* Tags */}
          {saved.tags.length > 0 && (
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 8 }}>
              {saved.tags.map((t: string) => <Badge key={t} tone="purple">{t}</Badge>)}
            </div>
          )}

          {/* Reviewed sections */}
          {saved.reviewed_sections.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase" }}>Reviewed</Mono>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 3 }}>
                {saved.reviewed_sections.map((s: string) => <Badge key={s} tone="emerald">{s.replace(/_/g, " ")}</Badge>)}
              </div>
            </div>
          )}

          {/* Private notes (recruiter-only) */}
          {editing ? (
            <div style={{ marginTop: 10 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, marginBottom: 8 }}>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  style={{ padding: "6px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12 }}
                >
                  {SAVED_STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <label style={{ fontSize: 11, color: TOKEN.muted }}>Fit:</label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={fitScore}
                    onChange={(e) => setFitScore(Number(e.target.value))}
                    style={{ width: 52, padding: "6px 8px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12 }}
                  />
                  <span style={{ fontSize: 11, color: TOKEN.muted }}>%</span>
                </div>
              </div>
              <textarea
                placeholder="Private notes (only visible to you)…"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                style={{
                  width: "100%",
                  padding: "8px 10px",
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 8,
                  fontSize: 12,
                  resize: "vertical",
                  boxSizing: "border-box",
                  marginBottom: 8,
                }}
              />
              <div style={{ display: "flex", gap: 6 }}>
                <Btn size="sm" variant="primary" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving…" : "Save"}
                </Btn>
                <Btn size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Btn>
              </div>
            </div>
          ) : (
            saved.private_notes && (
              <div
                style={{
                  padding: "6px 10px",
                  background: TOKEN.bg,
                  border: `1px solid ${TOKEN.line}`,
                  borderRadius: 6,
                  marginBottom: 8,
                }}
              >
                <Mono style={{ fontSize: 9, color: TOKEN.muted, display: "block", marginBottom: 2 }}>PRIVATE NOTES</Mono>
                <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{saved.private_notes}</p>
              </div>
            )
          )}

          <Mono style={{ fontSize: 10, color: TOKEN.muted, display: "block", marginTop: 4 }}>
            Saved: {new Date(saved.created_at).toLocaleDateString()}
          </Mono>
        </div>

        {/* Actions */}
        <div style={{ flexShrink: 0, display: "flex", gap: 6, flexDirection: "column" }}>
          {saved.public_slug && (
            <Link href={`/passport/${saved.public_slug}`} target="_blank">
              <Btn size="sm" variant="secondary">View passport</Btn>
            </Link>
          )}
          <Btn size="sm" variant="secondary" onClick={() => setEditing((e) => !e)}>
            Edit
          </Btn>
          <Btn size="sm" variant="danger" onClick={handleDelete}>
            Remove
          </Btn>
        </div>
      </div>
    </Card>
  )
}

export function RecruiterSavedCandidatesPanel() {
  const [email, setEmail] = useState("")
  const [emailInput, setEmailInput] = useState("")
  const [candidates, setCandidates] = useState<RecruiterSavedPassportResponse[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleLoad = async () => {
    if (!emailInput.trim()) return
    setLoading(true)
    setError(null)
    try {
      const results = await listRecruiterSavedPassports(emailInput.trim())
      setCandidates(results)
      setEmail(emailInput.trim())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }

  const handleUpdate = (id: string, update: Partial<RecruiterSavedPassportResponse>) => {
    setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, ...update } : c)))
  }

  const handleDelete = (id: string) => {
    setCandidates((prev) => prev.filter((c) => c.id !== id))
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Saved Candidates</h2>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
          Your shortlisted Work Passports. Notes and fit scores are private to you.
        </p>
      </div>

      {/* Email lookup */}
      <Card>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="email"
            placeholder="Your recruiter email"
            value={emailInput}
            onChange={(e) => setEmailInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLoad()}
            style={{
              flex: 1,
              padding: "9px 12px",
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 8,
              fontSize: 13,
            }}
          />
          <Btn variant="primary" onClick={handleLoad} disabled={loading || !emailInput.trim()}>
            {loading ? "Loading…" : "Load my shortlist"}
          </Btn>
        </div>
      </Card>

      {error && <ErrorState message={error} onRetry={handleLoad} />}

      {!loading && email && candidates.length === 0 && (
        <EmptyState
          icon="📌"
          title="No saved candidates"
          description="Visit a candidate's public Work Passport and click 'Save candidate' to add them to your shortlist."
        />
      )}

      {!loading && candidates.length > 0 && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{candidates.length} candidate{candidates.length !== 1 ? "s" : ""}</Mono>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {candidates.map((c) => (
              <CandidateCard
                key={c.id}
                saved={c}
                onUpdate={handleUpdate}
                onDelete={handleDelete}
              />
            ))}
          </div>
        </>
      )}

      <p style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center" }}>
        Private notes and fit scores are stored locally to your recruiter profile and are never shared with students.
      </p>
    </div>
  )
}
