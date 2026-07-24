"use client"

/**
 * Public Verified Work Passport — recruiter-first candidate page.
 *
 * Information architecture (progressive disclosure):
 *   L1  Candidate identity hero + short summary + featured projects + curated
 *       top skills — a recruiter understands the candidate in ~10–20 seconds.
 *   L2  Per-project detail and per-skill evidence, opened explicitly.
 *   L3  Full traceability lives in the linked Verified Build Reports and the
 *       public Skill Reports.
 *
 * The long "How to read this Passport" instructions and the recruiter
 * checklist are collapsed behind "Learn how verification works" — available,
 * never dominating. Identity comes from the consented Passport Profile: empty
 * fields are omitted, never placeholdered.
 */

import { useEffect, useMemo, useState } from "react"
import {
  fallbackSkillSlug,
  getPublicWorkPassportBySlug,
  proofChainFromSources,
  publicSkillReportPath,
  PROOF_CHAIN_STEPS,
  type PassportIdentity,
  type PublicPassportProject,
  type PublicPassportSkill,
  type PublicWorkPassport,
} from "@/lib/vbr-api"
import { publicSafeAvatarUrl } from "@/lib/passport-card"
import {
  Badge,
  Card,
  ErrorState,
  LoadingState,
  TOKEN,
  type BadgeTone,
} from "../../../../components/passport/shared"
import { EvidenceTraceList } from "../../../../components/passport/EvidenceTrace"
import { ProjectDefenseInspectionSection } from "../../../../components/passport/ProjectDefenseInspectionCard"
import { RecruiterCta } from "../../../../components/passport/RecruiterCta"
import {
  RecruiterReviewChecklist,
  RecruiterTrustFraming,
} from "../../../../components/passport/RecruiterTrustFraming"
import styles from "./public-passport.module.css"

const QUALITATIVE_LABEL_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  "Partially demonstrated": "amber",
  "Evidence observed": "emerald",
  "Supporting evidence": "sky",
  "Needs review": "rose",
  "Not assessed": "slate",
}

/**
 * Simplified recruiter-facing tier for a backend qualitative label. The
 * original label stays visible inside the expanded evidence detail — this is a
 * presentation grouping, never an upgrade (every non-"Demonstrated" label maps
 * to a weaker tier).
 */
export function skillTier(status: string): "Demonstrated" | "Supported" | "Emerging" {
  if (status === "Demonstrated") return "Demonstrated"
  if (
    status === "Partially demonstrated" ||
    status === "Evidence observed" ||
    status === "Supporting evidence"
  ) {
    return "Supported"
  }
  return "Emerging"
}

const TIER_TONE: Record<string, BadgeTone> = {
  Demonstrated: "emerald",
  Supported: "sky",
  Emerging: "slate",
}

/** Compact display label for an evidence source badge. */
const SOURCE_SHORT: Record<string, string> = {
  "GitHub Proof": "GitHub",
  "Document Proof": "Documents",
  "Website Proof": "Website",
  "Project Defense": "Project Defense",
  "Video Evidence": "Video",
  "VBR Report": "Verified Build Report",
}

function shortSource(label: string): string {
  return SOURCE_SHORT[label] ?? label
}

/**
 * Recruiter-facing display order for the backend's canonical skill taxonomy
 * (mirrors `skill_normalization.CATEGORY_ORDER`). Categories not listed here
 * (or absent on older payloads) fall through to the keyword fallback below.
 */
const CATEGORY_DISPLAY_ORDER = [
  "AI / Machine Learning",
  "GenAI / LLM",
  "MLOps / Deployment",
  "Backend / APIs",
  "Frontend",
  "Data / Analytics",
  "Database",
  "Cloud / DevOps",
  "Programming Language",
  "Security / Privacy",
  "Testing / Quality",
  "Documentation / Communication",
  "Product / System Design",
]

/** Keyword fallback for payloads without a backend `category`. */
const SKILL_GROUP_FALLBACK: { title: string; pattern: RegExp }[] = [
  {
    title: "AI / Machine Learning",
    pattern:
      /\b(ai|ml|machine.?learning|deep.?learning|neural|nlp|llm|vision|ocr|model|pytorch|tensorflow|scikit|data.?science)\b/i,
  },
  {
    title: "Backend / APIs",
    pattern:
      /\b(api|backend|server|fastapi|flask|django|express|node(\.js)?|rest|graphql|database|sql|postgres|supabase|auth)\b/i,
  },
  {
    title: "Frontend",
    pattern:
      /\b(frontend|react|next(\.js)?|ui|ux|css|html|design|product)\b/i,
  },
  {
    title: "Programming Language",
    pattern: /\b(python|javascript|typescript|java|golang|rust|c\+\+)\b/i,
  },
  {
    title: "Data / Analytics",
    pattern:
      /\b(data|cloud|aws|gcp|azure|docker|kubernetes|deploy|pipeline|etl|analytics|geospatial|infra)\b/i,
  },
]

function fallbackCategory(skillName: string): string {
  const match = SKILL_GROUP_FALLBACK.find((g) => g.pattern.test(skillName))
  return match ? match.title : "More skills"
}

/**
 * Group every skill by the backend's canonical taxonomy category (fallback:
 * deterministic keyword buckets). ALL skills are always grouped — grouping
 * never drops a skill; unknown categories collect under "More skills" last.
 */
export function groupSkills(
  skills: PublicPassportSkill[],
): { title: string; skills: PublicPassportSkill[] }[] {
  const byTitle = new Map<string, PublicPassportSkill[]>()
  for (const skill of skills) {
    const raw = skill.category?.trim() || fallbackCategory(skill.skill)
    const title = raw === "Other" ? "More skills" : raw
    const bucket = byTitle.get(title)
    if (bucket) bucket.push(skill)
    else byTitle.set(title, [skill])
  }
  const result: { title: string; skills: PublicPassportSkill[] }[] = []
  for (const title of CATEGORY_DISPLAY_ORDER) {
    const bucket = byTitle.get(title)
    if (bucket?.length) {
      result.push({ title, skills: bucket })
      byTitle.delete(title)
    }
  }
  // Any remaining category (backend "Other", fallback "More skills", or a new
  // backend category this client does not know yet) renders after the known
  // ones, in first-seen order — never dropped.
  const moreSkills = byTitle.get("More skills")
  byTitle.delete("More skills")
  for (const [title, bucket] of byTitle) {
    if (bucket.length) result.push({ title, skills: bucket })
  }
  if (moreSkills?.length) result.push({ title: "More skills", skills: moreSkills })
  return result
}

/** Stable in-page anchor id for a public skill row (safe slug only). */
function publicSkillAnchor(skillOrSlug: string): string {
  return `public-skill-${fallbackSkillSlug(skillOrSlug)}`
}

function initialsOf(name: string | null | undefined): string {
  return (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
}

// ── Section 1: Candidate identity hero ───────────────────────────────────────

function PassportHero({
  identity,
  fallbackName,
  fallbackHeadline,
  publishedAt,
}: {
  identity: PassportIdentity | null | undefined
  fallbackName: string | null
  fallbackHeadline?: string
  publishedAt: string | null
}) {
  const name = identity?.display_name ?? fallbackName ?? "Verified candidate profile"
  const headline = identity?.headline?.trim() || fallbackHeadline?.trim() || ""
  const avatar = publicSafeAvatarUrl(identity?.avatar_url ?? null)
  const educationLine = [identity?.degree, identity?.institution].filter(Boolean).join(" · ")
  // Fall back to the legacy education summary only when the consented profile
  // supplied no education fields at all.
  const legacyEducation = !educationLine ? identity?.education_summary?.trim() || "" : ""
  const metaLine = [
    identity?.graduation_year ? `Expected ${identity.graduation_year}` : "",
    identity?.location ?? "",
  ]
    .filter(Boolean)
    .join(" · ")
  const lastUpdated = identity?.last_updated ?? publishedAt

  const links: { label: string; href: string }[] = []
  if (identity?.github_url) links.push({ label: "GitHub", href: identity.github_url })
  if (identity?.linkedin_url) links.push({ label: "LinkedIn", href: identity.linkedin_url })
  if (identity?.portfolio_url) links.push({ label: "Portfolio", href: identity.portfolio_url })

  return (
    <Card style={{ padding: "clamp(18px, 4vw, 28px)" }}>
      <div className={styles.hero} data-testid="public-passport-hero">
        <div className={styles.heroAvatar}>
          {avatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatar}
              alt={`${name} profile photo`}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          ) : (
            <span style={{ color: TOKEN.indigo, fontWeight: 700, fontSize: 28 }}>
              {initialsOf(name) || "✓"}
            </span>
          )}
        </div>
        <div className={styles.heroBody}>
          <h1 className={styles.heroName} data-testid="passport-identity-name">
            {name}
          </h1>
          {identity?.pronunciation && (
            <p className={styles.heroMeta} style={{ fontSize: 12.5 }}>
              Pronounced {identity.pronunciation}
            </p>
          )}
          {headline && (
            <p className={styles.heroHeadline} data-testid="public-hero-headline">
              {headline}
            </p>
          )}
          {educationLine && (
            <p className={styles.heroMeta} data-testid="public-hero-education">
              {educationLine}
            </p>
          )}
          {legacyEducation && (
            <p className={styles.heroMeta} data-testid="public-hero-education">
              {legacyEducation}
            </p>
          )}
          {metaLine && <p className={styles.heroMeta}>{metaLine}</p>}
          <div className={styles.heroBadges}>
            <Badge tone="emerald">✓ {identity?.verification_label || "Verified Work Passport"}</Badge>
            {identity?.availability_label && (
              <span data-testid="public-hero-availability">
                <Badge tone="indigo">{identity.availability_label}</Badge>
              </span>
            )}
            {identity?.work_authorization_note && (
              <span data-testid="public-hero-work-auth">
                <Badge tone="slate">{identity.work_authorization_note}</Badge>
              </span>
            )}
          </div>
          {links.length > 0 && (
            <div className={styles.heroLinks} data-testid="public-hero-links">
              {links.map((link) => (
                <a
                  key={link.label}
                  className={styles.heroLink}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                >
                  {link.label} ↗
                </a>
              ))}
            </div>
          )}
          {lastUpdated && (
            <p className={styles.heroMeta} style={{ fontSize: 12 }}>
              Evidence-backed projects and skills · Updated{" "}
              {new Date(lastUpdated).toLocaleDateString()}
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}

// ── Section 3: Featured project card ─────────────────────────────────────────

function FeaturedProject({
  project,
  availableSkillAnchors,
}: {
  project: PublicPassportProject
  availableSkillAnchors: Set<string>
}) {
  const [detailOpen, setDetailOpen] = useState(false)
  const chain = project.proof_chain ?? proofChainFromSources(project.evidence_sources)
  const topSkills = (project.top_skills ?? []).slice(0, 6)
  const sources = project.evidence_sources.filter((s) => s !== "VBR Report").map(shortSource)

  return (
    <Card>
      <div data-testid="public-passport-project" className={styles.projectCard}>
        <h3 className={styles.projectTitle}>{project.project_title || "Project"}</h3>
        {project.project_summary && (
          <p className={styles.projectSummary}>{project.project_summary}</p>
        )}

        {/* 3–6 strongest skills, plain chips — status detail lives below. */}
        {topSkills.length > 0 ? (
          <div className={styles.chipRow} data-testid="public-project-top-skills">
            {topSkills.map((row) => {
              const anchor = publicSkillAnchor(row.skill)
              const linked = availableSkillAnchors.has(anchor)
              const chip = <span className={styles.skillChip}>{row.skill}</span>
              return linked ? (
                <a
                  key={row.skill}
                  href={`#${anchor}`}
                  data-testid="public-project-skill-link"
                  title={`See the evidence behind ${row.skill}`}
                  style={{ textDecoration: "none" }}
                >
                  {chip}
                </a>
              ) : (
                <span key={row.skill}>{chip}</span>
              )
            })}
          </div>
        ) : (
          project.claimed_skills.length > 0 && (
            <div className={styles.chipRow}>
              {project.claimed_skills.slice(0, 6).map((skill) => (
                <span key={skill} className={styles.skillChip}>
                  {skill}
                </span>
              ))}
            </div>
          )
        )}

        {/* Compact evidence coverage line. */}
        {sources.length > 0 && (
          <p className={styles.footNote} data-testid="public-project-evidence-line">
            Evidence: {sources.join(" · ")}
          </p>
        )}

        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <a
            data-testid="public-passport-report-link"
            href={project.public_report_path}
            className={styles.reportButton}
          >
            View Verified Build Report →
          </a>
          {/* Truth-gated outbound links: the backend only supplies these when a
              real, publicly-openable target exists — never a guess. */}
          {project.github_repo_url && (
            <a
              data-testid="public-project-github-link"
              href={project.github_repo_url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className={styles.disclosureButton}
              style={{ textDecoration: "none" }}
              title={project.github_repo_label ?? "Open the public repository"}
            >
              GitHub ↗
            </a>
          )}
          {project.live_url && (
            <a
              data-testid="public-project-live-link"
              href={project.live_url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className={styles.disclosureButton}
              style={{ textDecoration: "none" }}
            >
              Live site ↗
            </a>
          )}
          <button
            type="button"
            className={styles.disclosureButton}
            data-testid="public-project-detail-toggle"
            aria-expanded={detailOpen}
            onClick={() => setDetailOpen((v) => !v)}
          >
            {detailOpen ? "Hide evidence detail ▴" : "Evidence detail ▾"}
          </button>
        </div>

        {detailOpen && (
          <div
            data-testid="public-project-detail"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              padding: "12px 14px",
              background: TOKEN.bg,
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 10,
            }}
          >
            {/* Per-skill qualitative labels for this project. */}
            {topSkills.length > 0 && (
              <div className={styles.chipRow}>
                {topSkills.map((row) => (
                  <Badge key={row.skill} tone={QUALITATIVE_LABEL_TONE[row.status] ?? "slate"}>
                    {row.skill} · {row.status}
                  </Badge>
                ))}
              </div>
            )}
            {project.evidence_relationship_note && (
              <p data-testid="public-project-relationship-note" className={styles.footNote}>
                {project.evidence_relationship_note}
              </p>
            )}
            {/* Proof-chain completeness — honest ✓/– labels, never a number. */}
            <div data-testid="public-project-proof-chain" className={styles.chipRow}>
              {PROOF_CHAIN_STEPS.map((step) => (
                <span
                  key={step.key}
                  data-testid="public-proof-chain-item"
                  data-source={step.label}
                  data-present={chain[step.key] ? "true" : "false"}
                >
                  <Badge tone={chain[step.key] ? "emerald" : "slate"}>
                    {chain[step.key] ? "✓ " : "– "}
                    {shortSource(step.label)}
                  </Badge>
                </span>
              ))}
            </div>
            {chain.missing.length > 0 && (
              <p data-testid="public-project-gaps" className={styles.footNote}>
                Not included: {chain.missing.map(shortSource).join(", ")}.
              </p>
            )}
            {(project.project_defense_inspection?.length ?? 0) > 0 && (
              <ProjectDefenseInspectionSection
                cards={project.project_defense_inspection}
                testId="public-passport-project-defense-inspection"
              />
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

// ── Section 4: Curated skill row (expandable to full evidence detail) ────────

function SkillRow({ skill, passportSlug }: { skill: PublicPassportSkill; passportSlug: string }) {
  const [open, setOpen] = useState(false)
  const traces = skill.evidence_traces ?? []
  const strongest = skill.strongest_project ?? null
  const tier = skillTier(skill.status)
  const hasDetail =
    skill.projects.length > 0 ||
    skill.evidence_sources.length > 0 ||
    skill.evidence_chips.length > 0 ||
    traces.length > 0

  return (
    <div
      data-testid="public-passport-skill"
      id={publicSkillAnchor(skill.skill)}
      style={{ scrollMarginTop: 96, borderBottom: `1px solid ${TOKEN.line}` }}
    >
      <button
        type="button"
        className={styles.skillRowButton}
        data-testid="public-skill-expand-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ fontSize: 13.5, fontWeight: 600, color: TOKEN.ink, minWidth: 0, overflowWrap: "anywhere" }}>
          {skill.skill}
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <Badge tone={TIER_TONE[tier]}>{tier}</Badge>
          <span style={{ color: TOKEN.muted, fontSize: 12 }}>{open ? "▴" : "▾"}</span>
        </span>
      </button>

      {open && (
        <div
          data-testid="public-skill-detail"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            padding: "10px 12px 14px",
            marginBottom: 10,
            background: TOKEN.bg,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 10,
          }}
        >
          {/* The exact backend qualitative label — the tier above is only a
              presentation grouping. */}
          <div className={styles.chipRow}>
            <Badge tone={QUALITATIVE_LABEL_TONE[skill.status] ?? "slate"}>{skill.status}</Badge>
            {skill.evidence_sources.map((src) => (
              <Badge key={src} tone="slate">
                {shortSource(src)}
              </Badge>
            ))}
          </div>

          {hasDetail && strongest && (
            <div data-testid="public-skill-strongest-project" className={styles.footNote}>
              Strongest in <strong>{strongest.project_title}</strong>
              {strongest.skill_status ? ` — ${strongest.skill_status}` : ""}{" "}
              <a
                href={strongest.public_report_path}
                data-testid="public-strongest-project-link"
                style={{ color: TOKEN.indigo, fontWeight: 600, textDecoration: "none", whiteSpace: "nowrap" }}
              >
                View project evidence →
              </a>
            </div>
          )}

          {skill.projects.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {skill.projects.map((p, i) => (
                <div key={`${p.project_title}-${i}`} data-testid="public-skill-project-ref" className={styles.footNote}>
                  <strong style={{ color: TOKEN.inkSoft }}>{p.project_title}</strong>
                  {p.skill_status ? ` · ${p.skill_status}` : ""}
                  {" — "}
                  <a href={p.public_report_path} style={{ color: TOKEN.indigo, textDecoration: "none" }}>
                    View report →
                  </a>
                </div>
              ))}
            </div>
          )}

          {skill.evidence_chips.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {skill.evidence_chips.map((c, i) => (
                <div key={`${c.label}-${i}`} className={styles.footNote}>
                  <strong style={{ color: TOKEN.inkSoft }}>{c.label}</strong> — {c.short_summary}
                </div>
              ))}
            </div>
          )}

          {traces.length > 0 && <EvidenceTraceList traces={traces} />}

          {skill.limitations.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {skill.limitations.map((line, i) => (
                <li key={i} className={styles.footNote}>
                  {line}
                </li>
              ))}
            </ul>
          )}

          {(skill.aliases?.length ?? 0) > 0 && (
            <p data-testid="public-skill-aliases" className={styles.footNote} style={{ margin: 0 }}>
              Also recorded in evidence as: {skill.aliases?.join(", ")}
            </p>
          )}

          <a
            data-testid="public-skill-report-link"
            href={publicSkillReportPath(passportSlug, skill.skill_slug || fallbackSkillSlug(skill.skill))}
            style={{ fontSize: 12.5, fontWeight: 600, color: TOKEN.indigo, textDecoration: "none" }}
          >
            Open the full public skill report →
          </a>
        </div>
      )}
    </div>
  )
}

function SkillsSection({
  skills,
  passportSlug,
}: {
  skills: PublicPassportSkill[]
  passportSlug: string
}) {
  // EVERY evidence-backed skill is always rendered, grouped by the canonical
  // recruiter taxonomy — completeness is non-negotiable. The rows themselves
  // are compact (name + tier) and each expands to its evidence detail, so the
  // page stays scannable without hiding legitimate skills.
  const groups = useMemo(() => groupSkills(skills), [skills])

  if (skills.length === 0) {
    return (
      <Card>
        <p data-testid="public-passport-no-skills" className={styles.footNote}>
          Evidence not assessed yet.
        </p>
      </Card>
    )
  }

  return (
    <Card>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {groups.map((group) => (
          <div key={group.title} data-testid="public-skill-group">
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 8,
                margin: "2px 0 4px",
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: TOKEN.muted,
                }}
              >
                {group.title}
              </span>
              <span style={{ fontSize: 11, color: TOKEN.muted }}>
                {group.skills.length}
              </span>
            </div>
            {group.skills.map((skill) => (
              <SkillRow key={skill.skill} skill={skill} passportSlug={passportSlug} />
            ))}
          </div>
        ))}
      </div>
    </Card>
  )
}

// ── Section 6: compact transparency + collapsed methodology ──────────────────

function TransparencySection({ passport }: { passport: PublicWorkPassport }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <p className={styles.footNote} data-testid="public-passport-disclosure" style={{ textAlign: "center" }}>
        VeriBridge summarizes evidence submitted by the candidate. Recruiters should review linked
        reports and public sources before making decisions.
      </p>
      <button
        type="button"
        className={styles.disclosureButton}
        style={{ alignSelf: "center" }}
        data-testid="public-passport-methodology-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide verification details ▴" : "Learn how verification works ▾"}
      </button>
      {open && (
        <div
          data-testid="public-passport-methodology"
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
        >
          <RecruiterTrustFraming />
          <RecruiterReviewChecklist />
          {passport.limitations.length > 0 && (
            <Card>
              <div style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink, marginBottom: 8 }}>
                Limitations & transparency
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                {passport.limitations.map((line, i) => (
                  <li key={i} className={styles.footNote}>
                    {line}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {passport.verification_note && <p className={styles.footNote}>{passport.verification_note}</p>}
        </div>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

/** Projects shown before "View X more projects" (recruiter scan-first IA). */
const PROJECTS_COLLAPSED = 3

function SnapshotStat({ value, label }: { value: number; label: string }) {
  return (
    <div className={styles.snapshotStat} data-testid="public-snapshot-stat">
      <span className={styles.snapshotValue}>{value}</span>
      <span className={styles.snapshotLabel}>{label}</span>
    </div>
  )
}

export function PublicPassportView({ slug }: { slug: string }) {
  const [passport, setPassport] = useState<PublicWorkPassport | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAllProjects, setShowAllProjects] = useState(false)

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
        <span aria-hidden style={{ fontSize: 30, display: "block", marginBottom: 10 }}>🔒</span>
        <h1 style={{ fontSize: 20, color: TOKEN.ink, marginBottom: 10 }}>This Work Passport is currently private</h1>
        <p style={{ fontSize: 13, color: TOKEN.muted, lineHeight: 1.6 }}>
          The candidate has not made this Passport available for public viewing, or the link may be incorrect. If a
          candidate shared this link with you, ask them for an up-to-date Verified Work Passport link.
        </p>
      </div>
    )
  }

  if (error || !passport) return <ErrorState message={error ?? "Passport not found."} onRetry={load} />

  const sourceCounts = Object.entries(passport.evidence_source_counts).filter(([, n]) => n > 0)
  const availableSkillAnchors = new Set(passport.top_skills.map((s) => publicSkillAnchor(s.skill)))
  // Section 2 candidate summary: the student's own bio wins; the generic
  // passport summary is the fallback so older passports keep a description.
  const summaryText = passport.identity?.bio?.trim() || passport.summary
  const projects = passport.featured_projects
  const visibleProjects = showAllProjects ? projects : projects.slice(0, PROJECTS_COLLAPSED)
  const hiddenProjectCount = projects.length - visibleProjects.length
  const proofSourceCount = sourceCounts.filter(([label]) => label !== "VBR Report").length
  const vbrCount = passport.evidence_source_counts["VBR Report"] ?? 0

  return (
    <div data-testid="public-passport" className={styles.page}>
      {/* 1 — Candidate identity hero */}
      <PassportHero
        identity={passport.identity}
        fallbackName={passport.candidate_display_name}
        fallbackHeadline={passport.headline}
        publishedAt={passport.published_at}
      />

      {/* 2 — Candidate summary (short) */}
      {summaryText && (
        <p
          data-testid="public-passport-summary"
          className={styles.footNote}
          style={{ fontSize: 13.5, color: TOKEN.inkSoft, maxWidth: 720 }}
        >
          {summaryText}
        </p>
      )}

      {/* 2b — Recruiter snapshot: counts from canonical public records only. */}
      <div className={styles.snapshotRow} data-testid="public-passport-snapshot">
        <SnapshotStat value={projects.length} label={projects.length === 1 ? "Verified project" : "Verified projects"} />
        <SnapshotStat value={passport.top_skills.length} label="Evidence-backed skills" />
        <SnapshotStat value={proofSourceCount} label={proofSourceCount === 1 ? "Proof source" : "Proof sources"} />
        <SnapshotStat value={vbrCount} label={vbrCount === 1 ? "Verified Build Report" : "Verified Build Reports"} />
      </div>

      {/* 3 — Projects: strongest three first, every published project on demand */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 className={styles.sectionTitle}>
          Verified projects{projects.length > 0 ? ` (${projects.length})` : ""}
        </h2>
        {projects.length === 0 ? (
          <Card>
            <p data-testid="public-passport-no-projects" className={styles.footNote}>
              No published project reports yet.
            </p>
          </Card>
        ) : (
          <>
            {visibleProjects.map((project, i) => (
              <FeaturedProject
                key={`${project.public_report_path}-${i}`}
                project={project}
                availableSkillAnchors={availableSkillAnchors}
              />
            ))}
            {hiddenProjectCount > 0 && (
              <button
                type="button"
                className={styles.disclosureButton}
                data-testid="public-projects-show-all"
                onClick={() => setShowAllProjects(true)}
              >
                View {hiddenProjectCount} more {hiddenProjectCount === 1 ? "project" : "projects"} ▾
              </button>
            )}
            {showAllProjects && projects.length > PROJECTS_COLLAPSED && (
              <button
                type="button"
                className={styles.disclosureButton}
                data-testid="public-projects-show-less"
                onClick={() => setShowAllProjects(false)}
              >
                Show fewer projects ▴
              </button>
            )}
          </>
        )}
      </section>

      {/* 4 — Every evidence-backed skill, grouped by the canonical taxonomy */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 className={styles.sectionTitle}>
          Evidence-backed skills{passport.top_skills.length > 0 ? ` (${passport.top_skills.length})` : ""}
        </h2>
        <SkillsSection skills={passport.top_skills} passportSlug={slug} />
      </section>

      {/* 5 — Compact evidence coverage summary */}
      {sourceCounts.length > 0 && (
        <div className={styles.chipRow} style={{ justifyContent: "center" }} data-testid="public-passport-overview">
          {sourceCounts.map(([label, count]) => (
            <span key={label} data-testid="public-evidence-source-count">
              <Badge tone="slate">
                {shortSource(label)} · {count}
              </Badge>
            </span>
          ))}
        </div>
      )}

      {/* 6/7 — Transparency (compact) + methodology and deep detail collapsed */}
      <TransparencySection passport={passport} />

      {/* Recruiter CTA */}
      <div data-testid="public-passport-cta">
        <RecruiterCta />
      </div>
    </div>
  )
}
