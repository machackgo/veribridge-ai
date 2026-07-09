/**
 * Premium Beam Card model (Phase 1 of the Beam Card / Passport Handoff system).
 *
 * The Beam Card is the full-screen, in-person handoff surface at `/beam`: a
 * student opens it, shows it to a recruiter, and the recruiter scans one QR that
 * opens the live public Passport with no login. It is a *presentation* of
 * already-safe fields — everything here is derived from the same recruiter-safe
 * display data the Passport Card model uses ({@link buildPrivateCardModel}), plus
 * two public-only additions: the top proof-backed skills and the titles of
 * projects whose reports are actually published.
 *
 * Safety: the model never carries raw evidence, transcripts, signed URLs,
 * storage paths, internal ids, numeric scores, or anything from an unpublished
 * report. `topProjects` includes ONLY projects with a published public report
 * (`report.is_public`) — exactly the set the recruiter will find as featured
 * projects on the public Passport — so the card can never advertise a project
 * the scanned link doesn't show. The QR payload is the existing public Passport
 * URL (`{app}/p/{slug}`); Phase 2 will swap in the `/r/{code}` short link.
 */

import type { PrivateWorkPassport, WorkPassportStatus } from "@/lib/vbr-api"
import {
  PROOF_COVERAGE_ORDER,
  buildPrivateCardModel,
  publicSafeAvatarUrl,
  statusRank,
} from "@/lib/passport-card"

/** One top proof-backed skill row — name + qualitative status label only. */
export type BeamCardSkill = { name: string; status: string }

/** One verified (published-report) project — safe title only. */
export type BeamCardProject = { title: string }

/** How many top proof-backed skills the Beam Card face shows at most. */
export const MAX_BEAM_SKILLS = 5
/** How many verified project titles the Beam Card face shows at most. */
export const MAX_BEAM_PROJECTS = 3

export type BeamCardModel = {
  /** REAL display name only — backend placeholder copy is normalized to null. */
  name: string | null
  /** Up to two initials from the real name ("" when there is no real name). */
  initials: string
  /** Public-safe portrait URL (already sanitized), or null → initials fallback. */
  profileImageUrl: string | null
  headline: string
  /** University / degree / program line when available. */
  program: string | null
  /** Safe coarse region (country-level), or null. */
  region: string | null
  /** High-level role-area labels (the card model's default top areas). */
  roleAreas: string[]
  /** Top proof-backed skills — assessed skills only, strongest first. */
  topSkills: BeamCardSkill[]
  /** Verified projects — published-report projects only, safe titles only. */
  topProjects: BeamCardProject[]
  /** Present proof-source labels in canonical coverage order. */
  proofSources: string[]
  isPublished: boolean
  slug: string | null
  /** The ONE QR/share payload: the public Passport URL, or null while unpublished. */
  publicPassportUrl: string | null
}

/**
 * Build the Beam Card model from the owner's private passport + publish status.
 * All identity/role-area/proof-coverage fields come from the same safe card
 * model the Passport Card renders, so both surfaces obey identical safety rules.
 */
export function buildBeamCardModel(
  passport: PrivateWorkPassport,
  status: WorkPassportStatus,
): BeamCardModel {
  const card = buildPrivateCardModel(passport, status)

  // Top proof-backed skills: assessed only ("Not assessed" never fronts the
  // card), ranked by qualitative status, then project-attached evidence, then
  // breadth of proof sources — the same strength ordering the card model uses.
  const topSkills = passport.skills
    .filter((s) => s.status && s.status !== "Not assessed")
    .slice()
    .sort((a, b) => {
      const byStatus = statusRank(a.status) - statusRank(b.status)
      if (byStatus !== 0) return byStatus
      const byAttached = (b.project_count > 0 ? 1 : 0) - (a.project_count > 0 ? 1 : 0)
      if (byAttached !== 0) return byAttached
      const bySources = b.evidence_sources.length - a.evidence_sources.length
      if (bySources !== 0) return bySources
      return a.skill.localeCompare(b.skill)
    })
    .slice(0, MAX_BEAM_SKILLS)
    .map((s) => ({ name: s.skill, status: s.status }))

  // Verified projects = published public reports only. A project the student
  // has not published is invisible on the public Passport, so it must be
  // invisible here too — the Beam Card never advertises unpublished work.
  const topProjects = passport.projects
    .filter((p) => p.report?.is_public)
    .slice(0, MAX_BEAM_PROJECTS)
    .map((p) => ({ title: p.project_title }))

  return {
    name: card.name,
    initials: card.initials,
    profileImageUrl: card.profileImageUrl,
    headline: card.headline,
    program: card.program,
    region: card.region,
    roleAreas: card.capabilities.map((c) => c.label),
    topSkills,
    topProjects,
    proofSources: card.proofCoverage.filter((p) => p.present).map((p) => p.label),
    isPublished: card.isPublished,
    slug: card.slug,
    publicPassportUrl: card.publicPassportUrl,
  }
}

// ── Last-card offline fallback ────────────────────────────────────────────────
//
// The career-fair failure mode: the student opens /beam on venue Wi-Fi and the
// passport fetch fails. Because every BeamCardModel field is already public-safe
// (it mirrors what the public Passport shows), the last successfully built model
// can be cached on the student's own device and re-rendered as an honest
// "offline copy". Only a PUBLISHED card is ever cached — an unpublished passport
// has no public URL, so there is nothing safe (or useful) to show offline.

export const BEAM_CARD_CACHE_KEY = "veribridge-beam-card:last"

/** Cache the last successfully loaded, PUBLISHED Beam Card on this device. */
export function saveBeamCardCache(model: BeamCardModel): void {
  if (!model.isPublished || !model.publicPassportUrl) return
  try {
    window.localStorage.setItem(BEAM_CARD_CACHE_KEY, JSON.stringify(model))
  } catch {
    /* Storage blocked/full — the live card still rendered; skip the cache. */
  }
}

const isString = (v: unknown): v is string => typeof v === "string"

/**
 * Load the cached Beam Card, revalidating every field. The cache lives in
 * localStorage (user-editable), so this fails closed: only known fields are
 * copied, the portrait URL is re-sanitized, proof sources are filtered to the
 * canonical labels, and the public URL must be a real `/p/{slug}` link —
 * anything malformed yields null and the caller shows the normal error state.
 */
export function loadBeamCardCache(): BeamCardModel | null {
  try {
    const raw = window.localStorage.getItem(BEAM_CARD_CACHE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== "object" || parsed === null) return null
    const p = parsed as Record<string, unknown>

    const slug = isString(p.slug) && p.slug.trim() ? p.slug.trim() : null
    const publicPassportUrl = isString(p.publicPassportUrl) ? p.publicPassportUrl : null
    if (!slug || !publicPassportUrl || !publicPassportUrl.includes("/p/")) return null

    const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter(isString) : [])
    const name = isString(p.name) && p.name.trim() ? p.name.trim() : null

    return {
      name,
      initials: isString(p.initials) ? p.initials : "",
      profileImageUrl: publicSafeAvatarUrl(isString(p.profileImageUrl) ? p.profileImageUrl : null),
      headline: isString(p.headline) && p.headline.trim() ? p.headline : "Proof-backed technical candidate",
      program: isString(p.program) && p.program.trim() ? p.program : null,
      region: isString(p.region) && p.region.trim() ? p.region : null,
      roleAreas: strings(p.roleAreas),
      topSkills: Array.isArray(p.topSkills)
        ? p.topSkills
            .filter(
              (s): s is { name: string; status: string } =>
                typeof s === "object" && s !== null &&
                isString((s as Record<string, unknown>).name) &&
                isString((s as Record<string, unknown>).status),
            )
            .slice(0, MAX_BEAM_SKILLS)
            .map((s) => ({ name: s.name, status: s.status }))
        : [],
      topProjects: Array.isArray(p.topProjects)
        ? p.topProjects
            .filter(
              (pr): pr is { title: string } =>
                typeof pr === "object" && pr !== null && isString((pr as Record<string, unknown>).title),
            )
            .slice(0, MAX_BEAM_PROJECTS)
            .map((pr) => ({ title: pr.title }))
        : [],
      proofSources: PROOF_COVERAGE_ORDER.filter((label) => strings(p.proofSources).includes(label)),
      isPublished: true,
      slug,
      publicPassportUrl,
    }
  } catch {
    return null
  }
}
