"use client"

import { useEffect, useState } from "react"
import Link from "next/link"

import { getSkillReport, type SkillReport } from "@/lib/vbr-api"
import {
  Card,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../../../../components/passport/shared"
import { SkillReportView as SkillReportBody } from "../../../../../../../components/passport/VaultProofs"

/**
 * The SEPARATE private Skill Report page (route:
 * /student/vbr/passport/skills/[skillSlug]). It is NOT rendered inline inside the
 * Work Passport — the compact Passport skill card links here. The full,
 * recruiter-verifiable evidence (and the expensive website hydration) is loaded
 * lazily here for ONLY this one skill.
 */
export function SkillReportPageView({ skillSlug }: { skillSlug: string }) {
  const [report, setReport] = useState<SkillReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    getSkillReport(skillSlug)
      .then(setReport)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load skill report."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skillSlug])

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
      <Card>
        <SkillReportBody report={report} />
      </Card>
    </div>
  )
}
