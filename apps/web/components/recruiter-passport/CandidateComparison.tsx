"use client"

import { useState } from "react"
import {
  createCandidateComparison,
  type RecruiterCandidateComparisonResponse,
  type RecruiterCandidateResult,
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
  TOKEN,
} from "../passport/shared"

function CandidateResultCard({ result }: { result: RecruiterCandidateResult }) {
  const score = result.match_signal_score ?? 0
  const scoreColor = score >= 70 ? TOKEN.emerald : score >= 45 ? TOKEN.amber : TOKEN.rose

  return (
    <Card style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 12 }}>
        <div>
          <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>
            {result.student_display_name ?? "Candidate"}
          </span>
          {result.field && (
            <Badge tone="sky" style={{ marginLeft: 8 }}>{result.field}</Badge>
          )}
          {result.match_signal_label && (
            <p style={{ fontSize: 12, color: TOKEN.muted, margin: "4px 0 0" }}>{result.match_signal_label}</p>
          )}
        </div>
        <div style={{ textAlign: "center", flexShrink: 0 }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: scoreColor, lineHeight: 1 }}>
            {score > 0 ? `${score}%` : "—"}
          </div>
          <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase" }}>
            match signal
          </Mono>
        </div>
      </div>

      {score > 0 && (
        <ProgressBar
          value={score}
          color={scoreColor}
          height={6}
        />
      )}

      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
        {result.strong_skill_matches.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.emerald, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Strong Matches
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {result.strong_skill_matches.map((s: string) => <Badge key={s} tone="emerald">{s}</Badge>)}
            </div>
          </div>
        )}

        {result.partial_skill_matches.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.amber, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Partial Matches
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {result.partial_skill_matches.map((s: string) => <Badge key={s} tone="amber">{s}</Badge>)}
            </div>
          </div>
        )}

        {result.missing_required_skills.length > 0 && (
          <div>
            <Mono style={{ fontSize: 10, color: TOKEN.rose, textTransform: "uppercase", letterSpacing: "0.1em" }}>
              Missing Required
            </Mono>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
              {result.missing_required_skills.map((s: string) => <Badge key={s} tone="rose">{s}</Badge>)}
            </div>
          </div>
        )}

        {result.evidence_strength_summary && (
          <div
            style={{
              padding: "8px 10px",
              background: TOKEN.bg,
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 8,
            }}
          >
            <Mono style={{ fontSize: 9, color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 2 }}>
              Evidence Strength
            </Mono>
            <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{result.evidence_strength_summary}</p>
          </div>
        )}

        {result.recommended_follow_up && (
          <div
            style={{
              padding: "8px 10px",
              background: TOKEN.indigoSoft,
              border: `1px solid #c7d2fe`,
              borderRadius: 8,
            }}
          >
            <Mono style={{ fontSize: 9, color: TOKEN.indigo, textTransform: "uppercase", display: "block", marginBottom: 2 }}>
              Recommended Follow-up
            </Mono>
            <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0 }}>{result.recommended_follow_up}</p>
          </div>
        )}
      </div>

      {/* Disclaimer per-candidate */}
      <p style={{ fontSize: 10, color: TOKEN.muted, fontStyle: "italic", margin: "10px 0 0" }}>
        {result.disclaimer}
      </p>
    </Card>
  )
}

export function CandidateComparisonPanel({ savedPassportIds }: { savedPassportIds: string[] }) {
  const [requesterEmail, setRequesterEmail] = useState("")
  const [roleTitle, setRoleTitle] = useState("")
  const [requiredSkills, setRequiredSkills] = useState("")
  const [preferredSkills, setPreferredSkills] = useState("")
  const [selectedIds, setSelectedIds] = useState<string[]>(savedPassportIds.slice(0, 5))
  const [result, setResult] = useState<RecruiterCandidateComparisonResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCompare = async () => {
    if (!requesterEmail.trim() || selectedIds.length < 2) return
    setLoading(true)
    setError(null)
    try {
      const res = await createCandidateComparison({
        requester_email: requesterEmail.trim(),
        saved_passport_ids: selectedIds,
        role_title: roleTitle.trim() || null,
        required_skills: requiredSkills.split(",").map((s) => s.trim()).filter(Boolean),
        preferred_skills: preferredSkills.split(",").map((s) => s.trim()).filter(Boolean),
      })
      setResult(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Comparison failed")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>
          Candidate Comparison
        </h2>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
          Compare candidates against role requirements. These are match signals — not hiring decisions.
        </p>
      </div>

      {/* Comparison form */}
      <Card>
        <CardHeader title="Comparison Setup" icon="⚖️" />
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Your Email *
              </label>
              <input
                type="email"
                placeholder="you@company.com"
                value={requesterEmail}
                onChange={(e) => setRequesterEmail(e.target.value)}
                style={{ width: "100%", padding: "8px 12px", border: `1px solid ${TOKEN.line}`, borderRadius: 8, fontSize: 13, boxSizing: "border-box" }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Role Title
              </label>
              <input
                type="text"
                placeholder="Senior Backend Engineer"
                value={roleTitle}
                onChange={(e) => setRoleTitle(e.target.value)}
                style={{ width: "100%", padding: "8px 12px", border: `1px solid ${TOKEN.line}`, borderRadius: 8, fontSize: 13, boxSizing: "border-box" }}
              />
            </div>
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
              Required Skills (comma-separated)
            </label>
            <input
              type="text"
              placeholder="Python, FastAPI, PostgreSQL"
              value={requiredSkills}
              onChange={(e) => setRequiredSkills(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", border: `1px solid ${TOKEN.line}`, borderRadius: 8, fontSize: 13, boxSizing: "border-box" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
              Preferred Skills (comma-separated)
            </label>
            <input
              type="text"
              placeholder="Docker, TypeScript, AWS"
              value={preferredSkills}
              onChange={(e) => setPreferredSkills(e.target.value)}
              style={{ width: "100%", padding: "8px 12px", border: `1px solid ${TOKEN.line}`, borderRadius: 8, fontSize: 13, boxSizing: "border-box" }}
            />
          </div>

          {selectedIds.length < 2 && (
            <p style={{ fontSize: 12, color: TOKEN.rose }}>
              Select at least 2 saved candidates to compare.
            </p>
          )}

          {error && (
            <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6 }}>
              {error}
            </p>
          )}

          <Btn
            variant="primary"
            onClick={handleCompare}
            disabled={loading || selectedIds.length < 2 || !requesterEmail.trim()}
          >
            {loading ? "Comparing…" : `Compare ${selectedIds.length} candidates`}
          </Btn>
        </div>
      </Card>

      {loading && <LoadingState label="Generating comparison…" />}

      {result && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Card style={{ background: TOKEN.amberSoft, border: `1px solid #fde68a` }}>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
              <span style={{ fontSize: 18 }}>⚠️</span>
              <div>
                <p style={{ fontWeight: 700, fontSize: 13, color: "#92400e", margin: "0 0 4px" }}>
                  Important: This is a match signal analysis, not a hiring recommendation.
                </p>
                <p style={{ fontSize: 12, color: "#78350f", margin: 0, lineHeight: 1.5 }}>
                  {result.overall_disclaimer}
                </p>
              </div>
            </div>
          </Card>

          {result.role_title && (
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 14 }}>🎯</span>
              <div>
                <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase" }}>Role</Mono>
                <span style={{ fontWeight: 600, fontSize: 14, color: TOKEN.ink }}>{result.role_title}</span>
              </div>
              {result.required_skills.length > 0 && (
                <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginLeft: 8 }}>
                  {result.required_skills.map((s: string) => <Badge key={s} tone="indigo">{s}</Badge>)}
                </div>
              )}
            </div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {result.comparison_results
              .sort((a: RecruiterCandidateResult, b: RecruiterCandidateResult) => (b.match_signal_score ?? 0) - (a.match_signal_score ?? 0))
              .map((r: RecruiterCandidateResult, i: number) => (
                <div key={r.saved_passport_id || i}>
                  <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4, display: "block" }}>
                    #{i + 1}
                  </Mono>
                  <CandidateResultCard result={r} />
                </div>
              ))}
          </div>

          <Mono style={{ fontSize: 10, color: TOKEN.muted, textAlign: "right" }}>
            Comparison generated: {new Date(result.generated_at).toLocaleString()}
          </Mono>
        </div>
      )}

      {!result && !loading && savedPassportIds.length === 0 && (
        <EmptyState
          icon="⚖️"
          title="No candidates to compare"
          description="Save candidates from their public Work Passport pages first, then compare them here."
        />
      )}
    </div>
  )
}
