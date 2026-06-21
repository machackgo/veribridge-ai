"use client"

import { useEffect, useState } from "react"
import {
  getPublicWorkPassportBySlug,
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
  TOKEN,
  type BadgeTone,
} from "../../../../components/passport/shared"

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

function SkillChip({ skill }: { skill: PublicPassportSkill }) {
  const [open, setOpen] = useState(false)
  const hasDetail =
    skill.projects.length > 0 || skill.evidence_sources.length > 0 || skill.evidence_chips.length > 0

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
    <div data-testid="public-passport-skill" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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

          {skill.projects.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                Evidenced in
              </Mono>
              {skill.projects.map((p, i) => (
                <div
                  key={`${p.project_title}-${i}`}
                  data-testid="public-skill-project-ref"
                  style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
                >
                  <span style={{ fontSize: 12, color: TOKEN.ink, fontWeight: 600 }}>{p.project_title}</span>
                  <a
                    href={p.public_report_path}
                    style={{ fontSize: 11, color: TOKEN.indigo, textDecoration: "none" }}
                  >
                    View report →
                  </a>
                </div>
              ))}
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

function FeaturedProject({ project }: { project: PublicPassportProject }) {
  return (
    <Card>
      <div data-testid="public-passport-project" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink }}>{project.project_title || "Project"}</div>
        {project.project_summary && (
          <p style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>{project.project_summary}</p>
        )}
        {project.claimed_skills.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {project.claimed_skills.map((skill) => (
              <Badge key={skill} tone="indigo">
                {skill}
              </Badge>
            ))}
          </div>
        )}
        {project.evidence_sources.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {project.evidence_sources.map((src) => (
              <span key={src} data-testid="public-evidence-source-badge">
                <Badge tone={SOURCE_TONE[src] ?? "slate"}>{src}</Badge>
              </span>
            ))}
          </div>
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

  return (
    <div
      data-testid="public-passport"
      style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px", display: "flex", flexDirection: "column", gap: 16 }}
    >
      {/* Header */}
      <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 6 }}>
        <Mono style={{ fontSize: 11, letterSpacing: "0.16em", color: TOKEN.indigo, textTransform: "uppercase" }}>
          VeriBridge AI · Verified Work Passport
        </Mono>
        {passport.candidate_display_name && (
          <h1 style={{ fontSize: 26, color: TOKEN.ink, margin: 0 }}>{passport.candidate_display_name}</h1>
        )}
        <p style={{ fontSize: 15, color: TOKEN.inkSoft, margin: 0, fontWeight: 600 }}>{passport.headline}</p>
        <p style={{ fontSize: 13, color: TOKEN.muted, margin: "0 auto", maxWidth: 620, lineHeight: 1.6 }}>
          {passport.summary}
        </p>
        {passport.published_at && (
          <Mono style={{ fontSize: 11, color: TOKEN.muted }}>
            Published {new Date(passport.published_at).toLocaleDateString()}
          </Mono>
        )}
      </div>

      {/* Evidence source counts */}
      {sourceCounts.length > 0 && (
        <Card>
          <CardHeader title="Evidence by Source" eyebrow="Across featured projects" icon="📎" />
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

      {/* Top skills */}
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

      {/* Featured projects + reports */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Featured Verified Build Reports</h2>
        {passport.featured_projects.length === 0 ? (
          <Card>
            <p data-testid="public-passport-no-projects" style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>
              No public reports published yet.
            </p>
          </Card>
        ) : (
          passport.featured_projects.map((project, i) => (
            <FeaturedProject key={`${project.public_report_path}-${i}`} project={project} />
          ))
        )}
      </section>

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
