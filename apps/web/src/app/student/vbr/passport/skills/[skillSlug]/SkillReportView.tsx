"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"

import {
  getPrivateWorkPassport,
  getSkillReport,
  type PrivateWorkPassport,
  type SkillReport,
} from "@/lib/vbr-api"
import {
  Card,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../../../../components/passport/shared"
import { SkillReportView as SkillReportBody } from "../../../../../../../components/passport/VaultProofs"
import { buildSkillReportIntelligenceContext } from "../../../../../../../components/passport/SkillReportIntelligence"
import { ClaimEvidenceMapSection } from "../../../../../../../components/passport/ClaimEvidenceMapSection"

/**
 * The SEPARATE private Skill Report page (route:
 * /student/vbr/passport/skills/[skillSlug]). It is NOT rendered inline inside the
 * Work Passport — the compact Passport skill card links here. The full,
 * recruiter-verifiable evidence (and the expensive website hydration) is loaded
 * lazily here for ONLY this one skill.
 *
 * The private passport is fetched alongside the report ONLY to derive the
 * proof-relationship context (project-level / unmapped / suggested tiers). It is
 * an enhancement: any failure or absence fails closed and the report renders
 * from its own payload alone — never an error, never a guessed relationship.
 */
export function SkillReportPageView({ skillSlug }: { skillSlug: string }) {
  const [report, setReport] = useState<SkillReport | null>(null)
  const [passport, setPassport] = useState<PrivateWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getSkillReport(skillSlug)
      .then(setReport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load skill report."))
      .finally(() => setLoading(false))
    // Context-only fetch: never blocks or fails the report.
    Promise.resolve()
      .then(() => getPrivateWorkPassport())
      .then((p) => setPassport(p ?? null))
      .catch(() => setPassport(null))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skillSlug])

  const context = useMemo(() => buildSkillReportIntelligenceContext(passport, report), [passport, report])

  if (loading) return <LoadingState label="Loading skill evidence…" />
  if (error || !report) return <ErrorState message={error ?? "Skill report not found."} onRetry={load} />

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Link
        href="/student/vbr/passport"
        style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "none" }}
      >
        ← Back to Work Passport
      </Link>
      <Card>
        <div data-testid="skill-report-header" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h2 style={{ fontSize: 20, color: TOKEN.ink, margin: 0 }}>{report.skill}</h2>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>{report.category}</p>
        </div>
      </Card>
      {/* Canonical claim→evidence map — rendered verbatim from the backend
          synthesis; absent on legacy payloads (the section renders nothing). */}
      {report.claim_evidence_map && report.claim_evidence_map.claims.length > 0 && (
        <Card>
          <ClaimEvidenceMapSection map={report.claim_evidence_map} />
        </Card>
      )}
      <Card>
        <SkillReportBody report={report} context={context} />
      </Card>
    </div>
  )
}
