/**
 * Verified Passport Card model + selection logic.
 *
 * The Passport Card is the compact, recruiter/career-fair snapshot of a
 * candidate's evidence-backed profile — a digital-credential (ATM/ID-card) style
 * summary that answers, in 5–10 seconds: who is this candidate, what role areas
 * can they apply for, what high-level capabilities are evidence-backed, and how
 * do I open the full verified Work Passport. It is deliberately NOT a report: it
 * shows identity + high-level ROLE areas + proof coverage + a clear open/share
 * action, and links out to the full Passport for the detailed evidence. The card
 * face carries no QR/barcode — scanning/sharing lives in the surrounding controls.
 *
 * This module normalizes both the owner-only private passport and the
 * recruiter-safe public passport into ONE card model so the private preview and
 * the public Card render from the same shape and obey the same safety rules.
 *
 * Safety: every field here is derived from already-safe display fields (skill
 * names, qualitative status labels, evidence-source labels). It never surfaces
 * raw evidence, internal ids, numeric scores, or unpublished report routes. The
 * public builder only ever reads the recruiter-safe public passport payload.
 */

import {
  fallbackSkillSlug,
  type PrivateWorkPassport,
  type PublicWorkPassport,
  type WorkPassportStatus,
} from "@/lib/vbr-api"
import { buildPassportGraph } from "@/app/student/vbr/passport/passport-graph"
import { publicPassportCardUrl, publicPassportUrl } from "@/lib/app-url"
import {
  CAPABILITY_AREAS,
  buildCapabilityAggregates,
  capabilityStatusRank,
  matchAreaIndex,
  presentCapabilities,
  type CapabilityAggregate,
} from "@/lib/passport-capabilities"

/** Canonical proof-coverage order for the card's proof chips. */
export const PROOF_COVERAGE_ORDER = [
  "GitHub Proof",
  "Document Proof",
  "Website Proof",
  "Project Defense",
  "Video Evidence",
] as const

/**
 * Qualitative status ranking (never a numeric score) — strongest first, with
 * "Not assessed" last so it only appears on the card when nothing better exists.
 */
const STATUS_RANK: Record<string, number> = {
  Demonstrated: 0,
  "Evidence observed": 1,
  "Partially demonstrated": 2,
  "Supporting evidence": 3,
  "Needs review": 5,
  "Not assessed": 9,
}
export function statusRank(status: string): number {
  return STATUS_RANK[status] ?? 4
}

/**
 * How many high-level role areas the compact card face shows at most. The student
 * can pick which of the available role areas fill these slots (see the private
 * "Customize Passport Card" selector); when nothing is saved the card defaults to
 * the top-ranked areas.
 */
export const MAX_CARD_ROLE_AREAS = 6
const MAX_CARD_CAPABILITIES = MAX_CARD_ROLE_AREAS

/**
 * localStorage key for the student's chosen Passport Card role areas. Keyed by a
 * stable per-passport identifier (public slug when available, else a safe
 * fallback) so different passports on the same device don't clobber each other.
 * Frontend-only persistence for the MVP — there is no backend field for this yet,
 * so the private preview is the source of truth and the public card falls back to
 * the default top role areas.
 */
export const CARD_ROLE_AREAS_STORAGE_PREFIX = "veribridge-passport-card-role-areas:"

/** Build the per-passport localStorage key, falling back to a safe constant. */
export function cardRoleAreasStorageKey(idOrSlug: string | null | undefined): string {
  const id = idOrSlug?.trim()
  return `${CARD_ROLE_AREAS_STORAGE_PREFIX}${id && id.length > 0 ? id : "local"}`
}

// ── Capability grouping ───────────────────────────────────────────────────────

/**
 * The high-level role-area grouping is the ONE canonical mapping in
 * `@/lib/passport-capabilities` ({@link CAPABILITY_AREAS} + {@link matchAreaIndex}) —
 * the SAME source of truth the Work Passport "Role area" filter uses. The card
 * must never carry a second, incompatible capability mapping, so both surfaces
 * agree on which role area a skill belongs to (and every card chip exposes that
 * area's stable {@link CapabilityArea.id} as `roleAreaId`). Detailed evidence
 * skills (e.g. "Teachable Machine", "FastAPI", "Vercel Deployment") are grouped
 * into ONE role area by first-keyword match; `weak` areas (documentation /
 * communication) rank BELOW technical areas so they never dominate the chips.
 */

/** One skill's fields the grouping needs, normalized across private/public. */
type SkillInput = {
  name: string
  status: string
  slug: string
  /** Evidence-graph node key (private only) for same-page skill selection. */
  key?: string
  /** Distinct proof-type count supporting this skill (never a score). */
  proofCount: number
  /** This skill is demonstrated by an attached project (not vault-only). */
  projectAttached: boolean
}

export type PassportCardCapability = {
  /** High-level role area label, e.g. "Machine Learning". */
  label: string
  /**
   * Stable role-area id from the canonical {@link CapabilityArea.id} in
   * `@/lib/passport-capabilities` — the EXACT id the Work Passport "Role area"
   * filter uses. Clicking a card role chip drives that filter by this id (never a
   * low-level skill), so the card and the Role Area filter always agree.
   */
  roleAreaId: string
  /** Strongest qualitative status among the skills grouped into this area. */
  status: string
  /**
   * The strongest underlying skill this area maps to — the card deep-links a
   * chip to THIS skill's evidence so the recruiter lands on real, evidence-backed
   * proof in the Work Passport (never a fabricated capability link).
   */
  skill: string
  slug: string
  /** Present only for the private preview (same-page evidence-map selection). */
  key?: string
  /**
   * How many evidence-backed skills back this role area — a qualitative breadth
   * count (never a numeric trust/confidence score) shown next to each option in
   * the "Customize Passport Card" selector so the student can see which areas are
   * most supported.
   */
  evidenceCount: number
}

export type PassportCardProofCoverage = { label: string; present: boolean }

export type PassportCardModel = {
  /**
   * The candidate's REAL display name, or null when none exists. Backend
   * placeholder copy ("Verified candidate profile") is normalized to null here
   * (see {@link realDisplayName}) so it can never masquerade as a real name.
   */
  name: string | null
  /** Up to two initials from the REAL name (empty if no name — never "VP" from
   *  placeholder copy). */
  initials: string
  /**
   * Public-safe profile photo URL for the card's portrait, or null to fall back
   * to initials. Already sanitized (`publicSafeAvatarUrl`): never a
   * signed/tokenized storage URL, private storage path, or raw storage key.
   */
  profileImageUrl: string | null
  headline: string
  program: string | null
  /** Safe coarse location (country/region from the scrubbed identity payload —
   *  never a street/city-level location), or null when unavailable. */
  region: string | null
  /** Human status label ("Public passport live" / "Private only" / public label). */
  publicStatus: string
  isPublished: boolean
  slug: string | null
  /** Absolute public Passport URL (`{app}/p/{slug}`) when published. */
  publicPassportUrl: string | null
  /** Absolute public Passport Card URL (`{app}/card/{slug}`) when published. */
  cardUrl: string | null
  /**
   * Owner-only: the passport's public URL regardless of visibility (null until
   * a slug has ever been minted). While Private it opens the private-state
   * page, so the owner can verify what their link currently shows.
   */
  previewPublicUrl?: string | null
  /**
   * Default high-level role-area chips shown on the card face (grouped, not raw
   * skills), already capped to {@link MAX_CARD_ROLE_AREAS}. This is what the card
   * shows when the student has not customized their selection, and what the public
   * card always shows.
   */
  capabilities: PassportCardCapability[]
  /**
   * Every available role area (ranked, uncapped) the student can choose from in
   * the private "Customize Passport Card" selector. A superset of
   * {@link capabilities}; the private preview filters this by the saved selection.
   */
  availableCapabilities: PassportCardCapability[]
  /** Proof-coverage strip (canonical order; present flags only). */
  proofCoverage: PassportCardProofCoverage[]
  /** Compact evidence line ("N projects · M proof types · recruiter-safe"). */
  evidence: { projectCount: number; proofTypeCount: number }
}

/** Compare two skills by evidence strength (strongest first). */
function compareSkillStrength(a: SkillInput, b: SkillInput): number {
  const byStatus = statusRank(a.status) - statusRank(b.status)
  if (byStatus !== 0) return byStatus
  const byAttached = (b.projectAttached ? 1 : 0) - (a.projectAttached ? 1 : 0)
  if (byAttached !== 0) return byAttached
  const byProof = b.proofCount - a.proofCount
  if (byProof !== 0) return byProof
  return a.name.localeCompare(b.name)
}

/**
 * Group detailed evidence skills into ranked high-level role areas for the card.
 *
 * Selection logic (never a numeric ranking): only assessed skills contribute
 * ("Not assessed" is excluded so it never fronts as a primary capability);
 * technical areas outrank the weak documentation area; within that, areas are
 * ranked by their strongest skill's qualitative status, then project-attached
 * evidence, then breadth of proof types, then how many skills back the area. Each
 * chip carries its strongest underlying skill so the deep-link lands on real
 * evidence.
 *
 * Returns EVERY matched role area in ranked order (uncapped). Callers show the
 * default card face via {@link topCapabilities} and the full choosable list (the
 * private selector) via the whole array.
 */
function deriveCapabilities(skills: SkillInput[]): PassportCardCapability[] {
  const assessed = skills.filter((s) => s.status && s.status !== "Not assessed")
  if (assessed.length === 0) return []

  const groups = new Map<number, SkillInput[]>()
  for (const s of assessed) {
    const idx = matchAreaIndex(s.name)
    if (idx < 0) continue
    const list = groups.get(idx) ?? []
    list.push(s)
    groups.set(idx, list)
  }

  const areas = [...groups.entries()].map(([idx, members]) => {
    const rep = members.slice().sort(compareSkillStrength)[0]
    return {
      idx,
      area: CAPABILITY_AREAS[idx],
      rep,
      proofSum: members.reduce((sum, s) => sum + s.proofCount, 0),
      anyAttached: members.some((s) => s.projectAttached),
      bestStatus: Math.min(...members.map((s) => statusRank(s.status))),
      count: members.length,
    }
  })

  areas.sort((a, b) => {
    const weakA = a.area.weak ? 1 : 0
    const weakB = b.area.weak ? 1 : 0
    if (weakA !== weakB) return weakA - weakB
    if (a.bestStatus !== b.bestStatus) return a.bestStatus - b.bestStatus
    if (a.anyAttached !== b.anyAttached) return a.anyAttached ? -1 : 1
    if (b.proofSum !== a.proofSum) return b.proofSum - a.proofSum
    if (b.count !== a.count) return b.count - a.count
    return a.idx - b.idx
  })

  return areas.map(({ area, rep, count }) => ({
    label: area.label,
    roleAreaId: area.id,
    status: rep.status,
    skill: rep.name,
    slug: rep.slug,
    key: rep.key,
    evidenceCount: count,
  }))
}

/** The default card-face role areas: the top-ranked {@link MAX_CARD_ROLE_AREAS}. */
function topCapabilities(all: PassportCardCapability[]): PassportCardCapability[] {
  return all.slice(0, MAX_CARD_CAPABILITIES)
}

// ── Private card role areas = the Work Passport Role Area filter's catalog ─────
//
// The private preview must offer the SAME role areas the Work Passport "Role
// area" filter offers, so the "Customize Passport Card" editor can never show a
// smaller (or different) set than the filter. Both now consume the ONE canonical
// evidence aggregation ({@link buildCapabilityAggregates} + {@link
// presentCapabilities}) over the same Projects↔Skills graph — the exact source
// the filter's `roleAreaOptions` uses — instead of the card's own first-match
// skill grouping ({@link deriveCapabilities}), which collapsed multi-area skills
// (e.g. Backend vs. Cloud), dropped contextual areas (e.g. Computer Vision), and
// never surfaced the composite AI Product Engineering area.

/** Ids of the weak role areas (documentation/communication) — ranked below every
 *  technical area so they never fill a default card slot unless nothing else can. */
const WEAK_AREA_IDS = new Set(CAPABILITY_AREAS.filter((a) => a.weak).map((a) => a.id))

/**
 * Map ONE evidence-aggregated role area (the SAME canonical {@link
 * CapabilityAggregate} the Role Area filter renders) to a Passport Card chip.
 * `roleAreaId` is the canonical area id the card chip drives the filter by;
 * `evidenceCount` is how many connected lower-level skills back the area (the
 * qualitative breadth shown next to each selector option — never a score); the
 * chip carries the strongest underlying skill so any deep-link lands on real
 * evidence.
 */
function capabilityFromAggregate(agg: CapabilityAggregate): PassportCardCapability {
  const strongest = agg.skills[0]
  const skillName = strongest?.skillName ?? agg.label
  return {
    label: agg.label,
    roleAreaId: agg.id,
    status: agg.statusLabel,
    skill: skillName,
    slug: strongest?.skillSlug || fallbackSkillSlug(skillName),
    key: strongest?.skillKey,
    evidenceCount: agg.skills.length,
  }
}

/**
 * Default card-face role areas from the present aggregates: technical areas
 * before the weak documentation area, then strongest qualitative status, then
 * breadth of connected skills — capped to {@link MAX_CARD_ROLE_AREAS}. The full
 * (uncapped, canonical-order) list stays available for the selector.
 */
function defaultAggregateCapabilities(aggregates: CapabilityAggregate[]): PassportCardCapability[] {
  const ranked = aggregates.slice().sort((a, b) => {
    const weakA = WEAK_AREA_IDS.has(a.id) ? 1 : 0
    const weakB = WEAK_AREA_IDS.has(b.id) ? 1 : 0
    if (weakA !== weakB) return weakA - weakB
    const byStatus = capabilityStatusRank(a.statusLabel) - capabilityStatusRank(b.statusLabel)
    if (byStatus !== 0) return byStatus
    if (b.skills.length !== a.skills.length) return b.skills.length - a.skills.length
    return a.label.localeCompare(b.label)
  })
  return ranked.slice(0, MAX_CARD_CAPABILITIES).map(capabilityFromAggregate)
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function proofCoverageFromCounts(counts: Record<string, number> | undefined): PassportCardProofCoverage[] {
  const map = counts ?? {}
  return PROOF_COVERAGE_ORDER.map((label) => ({ label, present: (map[label] ?? 0) > 0 }))
}

/** Filter/sort proof-source labels into canonical coverage order. */
function orderedProofTypes(sources: string[] | undefined): string[] {
  const set = new Set(sources ?? [])
  return PROOF_COVERAGE_ORDER.filter((label) => set.has(label))
}

/**
 * Accept a profile photo URL only when it is public-safe, else return null so the
 * card falls back to safe initials. Guarantees the Passport Card never renders a
 * signed/tokenized storage URL, a private storage path, or a raw storage key:
 *  - rejects signed-URL / private-storage markers (S3/GCS/Supabase signatures,
 *    tokens, expiry params, `/object/sign/`, `/private/`);
 *  - allows only absolute `http(s)` URLs or root-relative paths — never `data:`,
 *    `blob:`, `file:`, `javascript:`, protocol-relative, or a bare storage key.
 * Legitimate CDN sizing query strings (e.g. `?w=200`) are preserved.
 */
export function publicSafeAvatarUrl(url: string | null | undefined): string | null {
  const raw = url?.trim()
  if (!raw) return null
  if (/(x-amz-|[?&](signature|token|expires|sig|sv|se)=|\/object\/sign\/|\/private\/)/i.test(raw)) {
    return null
  }
  if (/^https?:\/\//i.test(raw)) return raw
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw
  return null
}

/** Up to two initials from a display name (empty string when there is no name). */
function initialsFromName(name: string | null): string {
  if (!name) return ""
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return ""
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

// ── Identity realness — backend placeholders are NOT real profile data ────────

/**
 * The backend substitutes these exact strings when the student has no stored
 * name / headline (`_SAFE_DISPLAY_NAME` / `_DEFAULT_HEADLINE` in
 * `vbr_work_passport_service.py`). The card must treat them as "no data":
 * deriving initials from the placeholder ("Verified candidate profile" → "VP")
 * or presenting it as a role line would fabricate an identity the student never
 * provided. `model.name` is therefore only ever a REAL name — the placeholder
 * copy is applied at render time, where it is visibly fallback text.
 */
export const PLACEHOLDER_DISPLAY_NAME = "Verified candidate profile"
export const PLACEHOLDER_HEADLINE = "Verified Work Passport"

/** A real, human-entered display name — blank/placeholder values become null. */
export function realDisplayName(value: string | null | undefined): string | null {
  const v = value?.trim()
  if (!v) return null
  return v.toLowerCase() === PLACEHOLDER_DISPLAY_NAME.toLowerCase() ? null : v
}

/** A real headline / target-role line — blank/placeholder values become null. */
function realHeadline(value: string | null | undefined): string | null {
  const v = value?.trim()
  if (!v) return null
  return v.toLowerCase() === PLACEHOLDER_HEADLINE.toLowerCase() ? null : v
}

/** First name for personalized share copy ("Share Mohammed’s …"), or null. */
export function firstNameFrom(name: string | null | undefined): string | null {
  const first = name?.trim().split(/\s+/)[0]
  return first || null
}

/** Prefer a concise program name; fall back to the safe education summary. */
function programFromIdentity(program?: string | null, educationSummary?: string): string | null {
  const p = program?.trim()
  if (p) return p
  const e = educationSummary?.trim()
  return e || null
}

/**
 * Shown when the student has no real headline. Deliberately proof-language, not
 * an invented role claim ("AI Engineer / …") — the card must never assert a
 * target role the student didn't provide.
 */
const HEADLINE_FALLBACK = "Proof-backed technical candidate"

// ── Private preview (owner-only passport → card preview) ──────────────────────

/**
 * Build the card model for the PRIVATE Passport preview. Role areas are grouped
 * from the evidence-backed Projects↔Skills graph (strongest status first,
 * project-attached and multi-proof skills preferred, "Not assessed" excluded).
 * Each chip carries the graph node key so the preview can select the underlying
 * skill in the same-page Skills Evidence Map. Only recruiter-safe display fields
 * are ever read — never raw evidence, internal ids, or scores.
 */
export function buildPrivateCardModel(
  passport: PrivateWorkPassport,
  status: WorkPassportStatus,
): PassportCardModel {
  const graph = buildPassportGraph(passport)

  // Role areas come from the SAME canonical evidence aggregation the Work Passport
  // "Role area" filter uses (`presentCapabilities(buildCapabilityAggregates(...))`
  // over the same graph), so the "Customize Passport Card" selector always lists
  // the exact role-area catalog the filter offers — never the card's old
  // first-match subset. `availableCapabilities` mirrors the filter's option order
  // (canonical); the default card face ranks the strongest areas into its slots.
  const aggregates = presentCapabilities(buildCapabilityAggregates(graph.skills))
  const availableCapabilities = aggregates.map(capabilityFromAggregate)
  const capabilities = defaultAggregateCapabilities(aggregates)

  const proofCoverage = proofCoverageFromCounts(passport.evidence_source_counts)
  // Only a REAL name survives (backend placeholder copy → null → safe fallback
  // rendering, never fake "VP" initials).
  const name =
    realDisplayName(passport.identity?.display_name) ?? realDisplayName(passport.candidate_display_name)
  const isPublished = Boolean(status.is_published && status.public_slug)
  const slug = status.public_slug
  // The owner-only preview path is `/p/{slug}` whenever a slug has ever been
  // minted, independent of visibility — used to verify the private-state page.
  const previewSlug = status.preview_public_path?.replace(/^\/p\//, "")?.trim() || null

  return {
    name,
    initials: initialsFromName(name),
    profileImageUrl: publicSafeAvatarUrl(passport.identity?.avatar_url),
    headline: realHeadline(passport.identity?.headline) ?? realHeadline(passport.headline) ?? HEADLINE_FALLBACK,
    program: programFromIdentity(passport.identity?.program, passport.identity?.education_summary),
    region: passport.identity?.region?.trim() || null,
    publicStatus: isPublished ? "Public passport live" : "Private only",
    isPublished,
    slug: slug ?? null,
    publicPassportUrl: isPublished && slug ? publicPassportUrl(slug) : null,
    cardUrl: isPublished && slug ? publicPassportCardUrl(slug) : null,
    previewPublicUrl: previewSlug ? publicPassportUrl(previewSlug) : null,
    capabilities,
    availableCapabilities,
    proofCoverage,
    evidence: {
      projectCount: passport.projects.length,
      proofTypeCount: proofCoverage.filter((c) => c.present).length,
    },
  }
}

// ── Public card (recruiter-safe public passport → card) ───────────────────────

/**
 * Build the card model for the PUBLIC Passport Card from the recruiter-safe
 * public passport payload. Role areas are grouped from the server-selected,
 * published-only `top_skills`; chips deep-link out to the full public Passport by
 * skill slug. No private routes, ids, raw evidence, or scores are ever introduced.
 */
export function buildPublicCardModel(passport: PublicWorkPassport, slug: string): PassportCardModel {
  const skillInputs: SkillInput[] = passport.top_skills.map((s) => ({
    name: s.skill,
    status: s.status,
    slug: fallbackSkillSlug(s.skill),
    proofCount: orderedProofTypes(s.evidence_sources).length,
    projectAttached: (s.projects?.length ?? 0) > 0,
  }))
  const availableCapabilities = deriveCapabilities(skillInputs)
  const capabilities = topCapabilities(availableCapabilities)

  const proofCoverage = proofCoverageFromCounts(passport.evidence_source_counts)
  // Same realness rule as the private builder: placeholder copy is never a name.
  const name =
    realDisplayName(passport.identity?.display_name) ?? realDisplayName(passport.candidate_display_name)

  return {
    name,
    initials: initialsFromName(name),
    profileImageUrl: publicSafeAvatarUrl(passport.identity?.avatar_url),
    headline: realHeadline(passport.identity?.headline) ?? realHeadline(passport.headline) ?? HEADLINE_FALLBACK,
    program: programFromIdentity(passport.identity?.program, passport.identity?.education_summary),
    region: passport.identity?.region?.trim() || null,
    publicStatus: "Verified public passport",
    isPublished: true,
    slug,
    publicPassportUrl: publicPassportUrl(slug),
    cardUrl: publicPassportCardUrl(slug),
    capabilities,
    availableCapabilities,
    proofCoverage,
    evidence: {
      projectCount: passport.featured_projects.length,
      proofTypeCount: proofCoverage.filter((c) => c.present).length,
    },
  }
}
