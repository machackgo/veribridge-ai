"use client"

import { useEffect, useState } from "react"
import {
  fallbackSkillSlug,
  getPublicWorkPassportBySlug,
  matrixTraceLabel,
  proofChainFromSources,
  PROOF_CHAIN_STEPS,
  type PublicPassportProject,
  type PublicPassportSkill,
  type PublicWorkPassport,
} from "@/lib/vbr-api"
import {
  Badge,
  Card,
  CardHeader,
  ErrorState,
  LoadingState,
  Mono,
  PassportIdentityHeader,
  TOKEN,
  type BadgeTone,
} from "../../../../components/passport/shared"
import { EvidenceTraceList } from "../../../../components/passport/EvidenceTrace"
import { ProjectDefenseInspectionSection } from "../../../../components/passport/ProjectDefenseInspectionCard"

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Not assessed": "slate",
}

const SOURCE_TONE: Record<string, BadgeTone> = {
  "GitHub Proof": "indigo",
  "Document Proof": "sky",
  "Website Proof": "purple",
  "Project Defense": "emerald",
  "Video Evidence": "amber",
  "VBR Report": "emerald",
}

/** Stable in-page anchor id for a public skill row (safe slug only). */
function publicSkillAnchor(skillOrSlug: string): string {
  return `public-skill-${fallbackSkillSlug(skillOrSlug)}`
}

function SkillChip({ skill }: { skill: PublicPassportSkill }) {
  const [open, setOpen] = useState(false)
  const traces = skill.evidence_traces ?? []
  const strongest = skill.strongest_project ?? null
  const hasDetail =
    skill.projects.length > 0 ||
    skill.evidence_sources.length > 0 ||
    skill.evidence_chips.length > 0 ||
    traces.length > 0

  const headerStyle = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    justifyContent: "space-between",
    background: "none",
    border: "none",
    padding: 0,
    width: "100%",
    textAlign: "left" as const,
  }
  const headerInner = (
    <>
      <span style={{ fontSize: 13, fontWeight: 600, color: TOKEN.ink }}>
        {hasDetail && <span style={{ color: TOKEN.muted, marginRight: 6 }}>{open ? "▾" : "▸"}</span>}
        {skill.skill}
      </span>
      <Badge tone={QUALITATIVE_LABEL_TONE[skill.status] ?? "slate"}>{skill.status}</Badge>
    </>
  )

  return (
    <div
      data-testid="public-passport-skill"
      id={publicSkillAnchor(skill.skill)}
      style={{ display: "flex", flexDirection: "column", gap: 8, scrollMarginTop: 96 }}
    >
      {/* Skills with no safe drilldown stay non-interactive so the public
          passport exposes no buttons beyond intentional expand toggles. */}
      {hasDetail ? (
        <button
          type="button"
          data-testid="public-skill-expand-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          style={{ ...headerStyle, cursor: "pointer" }}
        >
          {headerInner}
        </button>
      ) : (
        <div style={headerStyle}>{headerInner}</div>
      )}

      {open && hasDetail && (
        <div
          data-testid="public-skill-detail"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: "10px 12px",
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 8,
          }}
        >
          {skill.evidence_sources.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {skill.evidence_sources.map((src) => (
                <Badge key={src} tone={SOURCE_TONE[src] ?? "slate"}>
                  {src}
                </Badge>
              ))}
            </div>
          )}

          {/* Skill → Project: where this skill is most strongly evidenced —
              published report link only, never a private route or id. */}
          {strongest && (
            <div
              data-testid="public-skill-strongest-project"
              style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", fontSize: 12, color: TOKEN.inkSoft }}
            >
              <span>
                This skill is strongest in <strong>{strongest.project_title}</strong>
                {strongest.skill_status ? ` — ${strongest.skill_status}` : ""}
              </span>
              <a
                href={strongest.public_report_path}
                data-testid="public-strongest-project-link"
                style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none", whiteSpace: "nowrap" }}
              >
                View project evidence →
              </a>
            </div>
          )}

          {skill.projects.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Evidenced in
              </Mono>
              {skill.projects.map((p, i) => {
                const projTraces = p.evidence_traces ?? []
                return (
                  <div
                    key={`${p.project_title}-${i}`}
                    data-testid="public-skill-project-ref"
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      padding: "8px 10px",
                      border: `1px solid ${TOKEN.line}`,
                      borderRadius: 8,
                      background: "#fff",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 12, color: TOKEN.ink, fontWeight: 600 }}>{p.project_title}</span>
                      {p.skill_status && (
                        <Badge tone={QUALITATIVE_LABEL_TONE[p.skill_status] ?? "slate"}>{p.skill_status}</Badge>
                      )}
                    </div>
                    {p.evidence_sources.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {p.evidence_sources.map((src) => (
                          <Badge key={src} tone={SOURCE_TONE[src] ?? "slate"}>
                            {src}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {/* Deep links straight to the exact trace cards in the public report. */}
                    {projTraces.length > 0 && (
                      <div data-testid="public-skill-project-trace-links" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {projTraces.map((t) => (
                          <a
                            key={t.trace_id}
                            href={`${p.public_report_path}#${t.evidence_anchor}`}
                            style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none" }}
                          >
                            {matrixTraceLabel(t)} →
                          </a>
                        ))}
                      </div>
                    )}
                    <a href={p.public_report_path} style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none" }}>
                      View report →
                    </a>
                  </div>
                )
              })}
            </div>
          )}

          {skill.evidence_chips.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Evidence snippets
              </Mono>
              {skill.evidence_chips.map((c, i) => (
                <div key={`${c.label}-${i}`} style={{ fontSize: 12, color: TOKEN.inkSoft }}>
                  <Mono style={{ fontSize: 11, color: TOKEN.ink }}>{c.label}</Mono> — {c.short_summary}
                </div>
              ))}
            </div>
          )}

          {traces.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Evidence traceability
              </Mono>
              <EvidenceTraceList traces={traces} />
            </div>
          )}

          {skill.limitations.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {skill.limitations.map((line, i) => (
                <li key={i} style={{ fontSize: 11, color: TOKEN.muted }}>
                  {line}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function FeaturedProject({
  project,
  availableSkillAnchors,
}: {
  project: PublicPassportProject
  /** Anchor ids of skills rendered in the Top Skills section below. */
  availableSkillAnchors: Set<string>
}) {
  const chain = project.proof_chain ?? proofChainFromSources(project.evidence_sources)
  const topSkills = project.top_skills ?? []
  return (
    <Card>
      <div data-testid="public-passport-project" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink }}>{project.project_title || "Project"}</div>
        {project.project_summary && (
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{project.project_summary}</p>
        )}
        {/* Project → Skill links: chips anchor to this skill's evidence in the
            Top Skills section on this same page — never to a private route. */}
        {topSkills.length > 0 ? (
          <div data-testid="public-project-top-skills" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {topSkills.map((row) => {
              // Derive the anchor from the display name (matching the Top
              // Skills section) so both sides always agree.
              const anchor = publicSkillAnchor(row.skill)
              const linked = availableSkillAnchors.has(anchor)
              const chip = (
                <Badge tone={QUALITATIVE_LABEL_TONE[row.status] ?? "indigo"}>
                  {row.skill} · {row.status}
                </Badge>
              )
              return linked ? (
                <a
                  key={row.skill}
                  href={`#${anchor}`}
                  data-testid="public-project-skill-link"
                  title={`See the evidence behind ${row.skill}`}
                  style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 4 }}
                >
                  {chip}
                  <span style={{ fontSize: 11, fontWeight: 600, color: TOKEN.indigo }}>View skill evidence ↓</span>
                </a>
              ) : (
                <span key={row.skill}>{chip}</span>
              )
            })}
          </div>
        ) : (
          project.claimed_skills.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {project.claimed_skills.map((skill) => (
                <Badge key={skill} tone="indigo">
                  {skill}
                </Badge>
              ))}
            </div>
          )
        )}
        {project.evidence_relationship_note && (
          <p
            data-testid="public-project-relationship-note"
            style={{ fontSize: 11, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}
          >
            {project.evidence_relationship_note}
          </p>
        )}
        {/* Proof-chain completeness: what evidence backs this project, and what
            is missing — honest transparency, labels only, never a number grade. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
            Evidence included
          </Mono>
          <div data-testid="public-project-proof-chain" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {PROOF_CHAIN_STEPS.map((step) => (
              <span
                key={step.key}
                data-testid="public-proof-chain-item"
                data-source={step.label}
                data-present={chain[step.key] ? "true" : "false"}
              >
                <Badge tone={chain[step.key] ? (SOURCE_TONE[step.label] ?? "emerald") : "slate"}>
                  {chain[step.key] ? "✓ " : "– "}
                  {step.label}
                </Badge>
              </span>
            ))}
          </div>
          {chain.missing.length > 0 && (
            <p data-testid="public-project-gaps" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
              Not included: {chain.missing.join(", ")}.
            </p>
          )}
        </div>
        {/* Recruiter-safe Project Defense inspection, only when the public
            passport DTO carries it. Fail-closed cards show a withheld
            placeholder; never raw transcript, segments, or internal ids. */}
        {(project.project_defense_inspection?.length ?? 0) > 0 && (
          <ProjectDefenseInspectionSection
            cards={project.project_defense_inspection}
            testId="public-passport-project-defense-inspection"
          />
        )}
        <a
          data-testid="public-passport-report-link"
          href={project.public_report_path}
          style={{
            alignSelf: "flex-start",
            padding: "8px 14px",
            borderRadius: 8,
            background: TOKEN.indigo,
            color: "#fff",
            fontSize: 13,
            fontWeight: 600,
            textDecoration: "none",
          }}
        >
          View Verified Build Report →
        </a>
      </div>
    </Card>
  )
}

export function PublicPassportView({ slug }: { slug: string }) {
  const [passport, setPassport] = useState<PublicWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    setNotFound(false)
    getPublicWorkPassportBySlug(slug)
      .then((data) => {
        if (!data) {
          setNotFound(true)
          return
        }
        setPassport(data)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load passport."))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  if (loading) return <LoadingState label="Loading Verified Work Passport…" />

  if (notFound) {
    return (
      <div
        data-testid="public-passport-not-found"
        style={{ maxWidth: 560, margin: "0 auto", padding: "64px 24px", textAlign: "center" }}
      >
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This passport is not available</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The link may have been unpublished by the candidate, or it may be incorrect. Ask the candidate for an
          up-to-date Verified Work Passport link.
        </p>
      </div>
    )
  }

  if (error || !passport) return <ErrorState message={error ?? "Passport not found."} onRetry={load} />

  const sourceCounts = Object.entries(passport.evidence_source_counts).filter(([, n]) => n > 0)
  // Skills actually rendered in the Top Skills section — a project skill chip
  // only becomes an in-page link when its target anchor exists.
  const availableSkillAnchors = new Set(passport.top_skills.map((s) => publicSkillAnchor(s.skill)))

  return (
    <div
      data-testid="public-passport"
      style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px", display: "flex", flexDirection: "column", gap: 16 }}
    >
      {/* Header — passport-style candidate identity area (recruiter-safe) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
        <PassportIdentityHeader
          identity={passport.identity}
          fallbackName={passport.candidate_display_name}
          fallbackHeadline={passport.headline}
          align="center"
        />
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "0 auto", maxWidth: 620, lineHeight: 1.6, textAlign: "center" }}>
          {passport.summary}
        </p>
        {passport.published_at && (
          <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
            Published {new Date(passport.published_at).toLocaleDateString()}
          </Mono>
        )}
      </div>

      {/* Evidence graph at a glance + evidence source counts */}
      {sourceCounts.length > 0 && (
        <Card>
          <CardHeader title="Evidence by Source" eyebrow="Across featured projects" icon="📎" />
          <p data-testid="public-passport-overview" style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 10px", lineHeight: 1.5 }}>
            {passport.featured_project_count} verified project
            {passport.featured_project_count === 1 ? "" : "s"} · {passport.top_skills.length} evidence-backed skill
            {passport.top_skills.length === 1 ? "" : "s"}. Every claim below links to inspectable evidence in a
            published Verified Build Report.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {sourceCounts.map(([label, count]) => (
              <span key={label} data-testid="public-evidence-source-count">
                <Badge tone={SOURCE_TONE[label] ?? "slate"}>
                  {label} · {count}
                </Badge>
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* Featured projects + reports — what this candidate built comes first */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Featured Verified Build Reports</h2>
        {passport.featured_projects.length === 0 ? (
          <Card>
            <p data-testid="public-passport-no-projects" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No published project reports yet.
            </p>
          </Card>
        ) : (
          passport.featured_projects.map((project, i) => (
            <FeaturedProject
              key={`${project.public_report_path}-${i}`}
              project={project}
              availableSkillAnchors={availableSkillAnchors}
            />
          ))
        )}
      </section>

      {/* Top skills — the second lens: what those projects prove */}
      <Card>
        <CardHeader title="Top Evidence-Backed Skills" eyebrow="Qualitative labels" icon="🧩" />
        {passport.top_skills.length === 0 ? (
          <p data-testid="public-passport-no-skills" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
            Evidence not assessed yet.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {passport.top_skills.map((skill) => (
              <SkillChip key={skill.skill} skill={skill} />
            ))}
          </div>
        )}
      </Card>

      {/* Limitations / transparency */}
      <Card>
        <CardHeader title="Limitations / Transparency" eyebrow="In good faith" icon="⚠️" />
        <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
          {passport.limitations.map((line, i) => (
            <li key={i} style={{ fontSize: 12, color: TOKEN.muted }}>
              {line}
            </li>
          ))}
        </ul>
      </Card>

      {/* Verification note */}
      {passport.verification_note && (
        <p style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.6, textAlign: "center", margin: 0 }}>
          {passport.verification_note}
        </p>
      )}

      {/* Recruiter CTA */}
      <Card>
        <div data-testid="public-passport-cta" style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 10, padding: "8px 0" }}>
          <h2 style={{ fontSize: 16, color: TOKEN.ink, margin: 0 }}>Hiring? Verify what candidates actually built.</h2>
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
            Request an evidence-backed Verified Build Report from your candidates, or learn how VeriBridge works.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
            <a
              href="/recruiters"
              style={{ padding: "8px 14px", borderRadius: 8, background: TOKEN.indigo, color: "#fff", fontSize: 13, fontWeight: 600, textDecoration: "none" }}
            >
              Request a VBR from your candidates
            </a>
            <a
              href="/recruiters"
              style={{ padding: "8px 14px", borderRadius: 8, border: `1px solid ${TOKEN.line}`, background: "#fff", color: TOKEN.inkSoft, fontSize: 13, fontWeight: 600, textDecoration: "none" }}
            >
              See how VeriBridge works
            </a>
          </div>
        </div>
      </Card>
    </div>
  )
}
