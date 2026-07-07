/**
 * passport-capabilities.ts — the ONE canonical high-level role/capability layer.
 *
 * A recruiter does not search raw skills ("Docker", "Browser APIs", "Model
 * Training"). They ask role-level questions: "Is this person ready for a Computer
 * Vision role? An MLOps role? Backend APIs?". This module groups the detailed,
 * evidence-backed Work-Passport skills into recruiter-facing ROLE AREAS and,
 * crucially, aggregates the underlying evidence honestly:
 *   • which projects support the capability,
 *   • which exact skills inside those projects support it,
 *   • which proof types back each skill→project relationship,
 *   • what gaps still remain.
 *
 * It is deliberately NOT a score/rank/readiness guarantee. The language it emits
 * is "role-relevant evidence", "supported by these projects", "needs stronger
 * proof in …" — never "hire-ready", "guaranteed", or a number.
 *
 * SINGLE SOURCE OF TRUTH. Both surfaces read this one mapping:
 *   1. The Passport Card top role chips ({@link matchAreaIndex} via passport-card).
 *   2. The Work Passport "Role area" filter + capability evidence summary
 *      ({@link buildCapabilityAggregates}).
 * There must be no second hardcoded capability mapping anywhere else.
 *
 * Everything here is derived from already-safe display fields the Passport graph
 * exposes (skill names, qualitative status labels, canonical proof-type labels,
 * project titles). It never surfaces raw evidence, internal ids, file paths, or
 * numeric scores.
 */

import type { PassportSkillNode, SkillProjectEvidence } from "@/app/student/vbr/passport/passport-graph"
import { SKILL_PROOF_TYPE_ORDER } from "@/app/student/vbr/passport/passport-graph"

// ── Qualitative status ranking (shared with the card) ─────────────────────────

/**
 * Qualitative status ranking — strongest first, never a numeric score. "Not
 * assessed" is last so it only surfaces when nothing better exists. Exported so
 * the Passport Card and the capability aggregator rank evidence identically.
 */
export const CAPABILITY_STATUS_RANK: Record<string, number> = {
  Demonstrated: 0,
  "Evidence observed": 1,
  "Partially demonstrated": 2,
  "Supporting evidence": 3,
  "Needs review": 5,
  "Not assessed": 9,
}

export function capabilityStatusRank(status: string): number {
  return CAPABILITY_STATUS_RANK[status] ?? 4
}

// ── Capability layers (for the composite AI Product Engineering area) ──────────

/**
 * The engineering LAYER a role area represents. AI Product Engineering is a
 * COMPOSITE area that is only claimed when evidence spans ≥2 distinct layers with
 * AI/ML at the core (AI/ML + product UI, or AI/ML + API/backend, or AI/ML +
 * deployment) — so it never over-claims from a single-layer project.
 */
export type CapabilityLayer = "ai_ml" | "backend" | "frontend" | "deployment" | "data" | "other"

// ── Capability area definitions ───────────────────────────────────────────────

export type CapabilityArea = {
  /** Stable slug id (kebab-case of the label). */
  id: string
  label: string
  /**
   * Skill-name keywords that map DIRECTLY to this area (primary evidence). A
   * skill whose (lowercased) name contains one of these belongs to the area
   * regardless of which project it appears in.
   */
  keywords: string[]
  /**
   * Skill-name keywords that map to this area ONLY when the project provides the
   * area's context (e.g. "Machine Learning" counts toward Computer Vision only in
   * an image/classification project). This is what keeps a generic ML project out
   * of the Computer Vision role area while an image-classification project's ML
   * evidence is correctly included.
   */
  contextualKeywords?: string[]
  /**
   * Project signal keywords. A contextual skill is unlocked for this area when
   * the project's title contains one of these, OR the same project also carries a
   * PRIMARY skill of this area. Never used for primary skills.
   */
  contextKeywords?: string[]
  /**
   * Ranked BELOW technical areas on the card so documentation/communication never
   * dominates the role chips unless nothing technical exists.
   */
  weak?: boolean
  /** Which evidence layer this area contributes to the composite AIPE area. */
  layer?: CapabilityLayer
  /**
   * Composite area (AI Product Engineering): it has no direct keywords; its rows
   * are drawn from the {@link composeFrom} layers and it is only "present" when
   * those rows span ≥2 distinct layers including AI/ML.
   */
  composite?: boolean
  composeFrom?: CapabilityLayer[]
}

/**
 * The canonical role areas. ORDER MATTERS for the Passport Card's first-match
 * grouping ({@link matchAreaIndex}): more specific / higher-value areas come
 * first, so e.g. "FastAPI" lands in Backend APIs before a generic area. Composite
 * areas carry no keywords, so they never win a first-match and never appear as a
 * raw-skill-derived card chip — they surface only through the evidence-aggregated
 * Role Area filter.
 */
export const CAPABILITY_AREAS: CapabilityArea[] = [
  {
    id: "machine-learning",
    label: "Machine Learning",
    layer: "ai_ml",
    keywords: [
      "machine learning", "deep learning", "model training", "model train",
      "teachable machine", "neural network", "neural", "tensorflow", "pytorch",
      "keras", "scikit", "scikit-learn", "supervised learning", "unsupervised",
      "reinforcement", "predictive model", "ml model", "regression",
      "feature engineering", "model inference", "model evaluation", "evaluation",
      "classifier", "dataset",
    ],
  },
  {
    id: "computer-vision",
    label: "Computer Vision",
    layer: "ai_ml",
    keywords: [
      "computer vision", "object detection", "image segmentation", "image recognition",
      "image classification", "opencv", "face detection", "facial", "convolutional",
      "cnn", "image processing", "pose detection", "ocr", "webcam", "frame analysis",
      // NB: no bare "visual" — it substring-matches "Data Visualization" (a Data
      // Science skill). Genuine visual projects are caught by contextKeywords.
    ],
    // ML-family skills count toward CV only inside an image/vision project.
    contextualKeywords: [
      "machine learning", "deep learning", "model training", "model train",
      "teachable machine", "neural network", "neural", "classification",
      "image", "prediction", "inference",
    ],
    contextKeywords: [
      "image", "vision", "classification", "detection", "ocr", "photo", "camera",
      "webcam", "visual", "teachable", "recognition", "segmentation", "opencv",
      "cnn", "pose", "face", "facial", "picture", "video frame",
    ],
  },
  {
    id: "nlp-llm",
    label: "NLP / LLM",
    layer: "ai_ml",
    keywords: [
      "nlp", "natural language", "text classification", "llm", "large language model",
      "prompt", "langchain", "openai", "generative ai", "genai", "chatbot",
      "retrieval augmented", "rag", "embedding", "transformer", "bert", "gpt",
      "named entity", "sentiment", "tokeniz", "text extraction", "summariz",
    ],
    // OCR maps to NLP only in a text-extraction project (else it is CV).
    contextualKeywords: ["ocr", "text"],
    contextKeywords: ["text", "document", "language", "chat", "nlp", "transcript", "extract"],
  },
  {
    id: "data-science-applied-ai",
    label: "Data Science / Applied AI",
    layer: "data",
    keywords: [
      "data science", "data analysis", "data analytics", "applied ai", "pandas",
      "numpy", "geospatial", "statistics", "statistical", "analytics", "eda",
      "exploratory data", "feature analysis", "data visualization", "visualization",
      "dashboard", "charts", "chart", "risk scoring", "jupyter", "python", "sql",
      "postgres", "postgresql",
    ],
  },
  {
    id: "backend-apis",
    label: "Backend APIs",
    layer: "backend",
    keywords: [
      "fastapi", "backend api", "backend", "rest api", "rest", "restful", "graphql",
      "flask", "django", "express", "node backend", "server-side", "service layer",
      "sql", "postgres", "postgresql", "supabase", "database", "endpoint",
      "microservice", "authentication", "authorization", "schema", "migration", "api",
    ],
  },
  {
    id: "cloud-mlops",
    label: "Cloud / MLOps",
    layer: "deployment",
    keywords: [
      "docker", "kubernetes", "google cloud", "gcp", "aws", "azure", "vercel",
      "render", "railway", "ci/cd", "cicd", "devops", "deployment", "deploy",
      "mlops", "terraform", "pipeline", "serverless", "cloud run", "vertex",
      "environment config", "environment", "model serving", "inference service",
      "monitoring", "production", "supabase", "backend api", "fastapi", "cloud",
      "api",
    ],
  },
  {
    id: "full-stack-frontend-ai",
    label: "Full-Stack / Frontend AI",
    layer: "frontend",
    keywords: [
      "javascript", "typescript", "react", "next.js", "nextjs", "frontend",
      "front-end", "browser api", "browser", "html", "css", "tailwind", "vue",
      "svelte", "web app", "interactive demo", "ui/ux", "user interface",
      "user interaction", "product workflow", "website proof", "form", "dashboard",
    ],
  },
  {
    id: "software-engineering",
    label: "Software Engineering",
    layer: "other",
    keywords: [
      "java", "c++", "c#", "golang", "rust", "kotlin", "algorithm",
      "data structure", "object-oriented", "software engineering",
      "software development", "version control", "git", "unit test", "testing",
    ],
  },
  {
    id: "documentation-communication",
    label: "Documentation & Communication",
    weak: true,
    layer: "other",
    keywords: [
      "documentation", "technical writing", "technical documentation",
      "communication", "presentation", "report writing", "writing",
    ],
  },
  {
    id: "ai-product-engineering",
    label: "AI Product Engineering",
    composite: true,
    // Present only when evidence spans AI/ML + at least one product layer.
    composeFrom: ["ai_ml", "backend", "frontend", "deployment"],
    keywords: [],
  },
]

/**
 * One-line, recruiter-readable PURPOSE for each role area — what capability
 * pattern the area actually represents. Purely descriptive (never a claim about
 * the candidate); the narrative pairs it with the candidate's real connected
 * evidence. Keyed by {@link CapabilityArea.id}.
 */
export const ROLE_AREA_PURPOSE: Record<string, string> = {
  "machine-learning":
    "training and evaluating models, working with datasets and features, and connecting model behaviour to project outputs",
  "computer-vision":
    "using image and visual workflows — classification, detection, and browser or model outputs backed by visual evidence",
  "nlp-llm":
    "working with language, text, and LLM-driven workflows, and connecting model output to real product behaviour",
  "data-science-applied-ai":
    "using analysis, data transformation, modelling, and decision-oriented outputs",
  "backend-apis":
    "building service and API layers that connect product workflows, data, and user-facing systems",
  "cloud-mlops":
    "connecting models and products to deployment, APIs, environment/runtime, and production-oriented proof",
  "full-stack-frontend-ai":
    "building user-facing AI workflows, browser interfaces, and product-interaction evidence",
  "software-engineering":
    "applying core programming, algorithms, and engineering practices across projects",
  "documentation-communication":
    "documenting and communicating technical work so it can be understood and reviewed",
  "ai-product-engineering":
    "connecting technical implementation across layers into an end-to-end product workflow with recruiter-safe proof",
}

/** Purpose line for an area id, with a safe generic fallback. */
export function roleAreaPurpose(id: string): string {
  return ROLE_AREA_PURPOSE[id] ?? "connecting role-relevant lower-level skills to project evidence"
}

/** All composeFrom areas resolved to their non-composite definitions. */
const COMPOSITE_AREA = CAPABILITY_AREAS.find((a) => a.composite) ?? null

function includesAny(haystack: string, needles: string[]): boolean {
  return needles.some((n) => haystack.includes(n))
}

/**
 * First capability area whose PRIMARY keyword the skill name contains, else -1.
 * Used by the Passport Card to group each detailed skill into ONE role chip.
 * Composite areas (no keywords) are never returned.
 */
export function matchAreaIndex(name: string): number {
  const n = name.toLowerCase()
  for (let i = 0; i < CAPABILITY_AREAS.length; i += 1) {
    const area = CAPABILITY_AREAS[i]
    if (area.keywords.length > 0 && area.keywords.some((k) => n.includes(k))) return i
  }
  return -1
}

// ── Capability evidence aggregation (Role Area filter + summary) ───────────────

/** One skill→project evidence relationship that supports a role area. */
export type CapabilityEvidenceRow = {
  skillKey: string
  skillName: string
  /** Skill slug for the owner-only skill-report link (already safe). */
  skillSlug: string
  projectId: string
  projectTitle: string
  /** Owner-only project-report route for this project (always present). */
  reportPath: string
  publicReportPath: string | null
  reportIsPublic: boolean
  /** Canonical proof-type labels supporting THIS skill in THIS project. */
  proofTypes: string[]
  /** This skill's qualitative status in this project (never a score). */
  skillStatus: string
  /**
   * True when the skill was included via PROJECT CONTEXT rather than a direct
   * keyword (e.g. Machine Learning counted for Computer Vision because the project
   * is an image-classification project). Lets the UI phrase it honestly.
   */
  contextual: boolean
}

/** One connected lower-level skill that supports a role area. */
export type CapabilitySkillSupport = {
  skillKey: string
  skillName: string
  skillSlug: string
  /** Strongest qualitative status among this skill's role-area rows. */
  status: string
  /** Titles of the projects (within this role area) that demonstrate this skill. */
  projectTitles: string[]
  /** Union of proof types this skill contributes to the role area (canonical order). */
  proofTypes: string[]
  /** True when this skill was linked via project context, not a direct keyword. */
  contextual: boolean
  /** Plain-language, honest reason this skill connects to the role area. */
  reason: string
}

/** A supported project inside a role area, with its underlying skills + proof. */
export type CapabilityProjectSupport = {
  projectId: string
  projectTitle: string
  /** Underlying skill names this project contributes to the capability. */
  skillNames: string[]
  /** Underlying skill refs (name + slug) for per-skill report links. */
  skillRefs: { name: string; slug: string }[]
  /** Union of proof types across this project's supporting rows (canonical order). */
  proofTypes: string[]
  /** Strongest qualitative status among this project's supporting rows. */
  status: string
  /** Owner-only project-report route + published-report info. */
  reportPath: string
  publicReportPath: string | null
  reportIsPublic: boolean
  /** Plain-language reason this project supports the role area (honest). */
  reason: string
  /** True when any supporting skill was included via project context, not directly. */
  contextual: boolean
}

/** The aggregated, evidence-grounded view of one role area. */
export type CapabilityAggregate = {
  id: string
  label: string
  composite: boolean
  /** Has ≥1 evidence-backed skill→project row (for composite: multi-layer met). */
  present: boolean
  rows: CapabilityEvidenceRow[]
  /** Connected lower-level skills (strongest first). */
  skills: CapabilitySkillSupport[]
  /** Supported projects (strongest first). */
  projects: CapabilityProjectSupport[]
  /** Distinct underlying skill names across all rows. */
  skillNames: string[]
  /** Union of proof types across all rows (canonical order). */
  proofTypes: string[]
  /** Qualitative role-level status label (never a number). */
  statusLabel: string
  /** Strongest supported project, or null. */
  strongest: CapabilityProjectSupport | null
  /** Counts-based evidence sentence ("… N connected skills across M projects …"). */
  summary: string
  /** One-line purpose of the role area (what the capability pattern means). */
  purpose: string
  /**
   * Rich, fact-grounded "why this role area is supported" explanation — 1–2
   * recruiter-readable paragraphs built from the exact connected skills,
   * projects, and proof sources. Falls back to a single conservative paragraph
   * when evidence is thin. Never fabricates evidence or claims a score.
   */
  narrative: string[]
  /** Legacy single-sentence "why" (kept = the first narrative paragraph). */
  why: string
  /** Ordered evidence-chain node labels (skills → project → proofs) for the connector row. */
  evidenceChain: string[]
  /** Honest gaps / what still needs stronger proof (never fabricated). */
  gaps: string[]
  /** Distinct layers with evidence (composite areas only). */
  layers: CapabilityLayer[]
}

function orderProofTypes(sources: Iterable<string>): string[] {
  const set = new Set(sources)
  return SKILL_PROOF_TYPE_ORDER.filter((label) => set.has(label))
}

/** Does a skill map to an area directly, contextually (given project), or not? */
function skillAreaMatch(
  area: CapabilityArea,
  skillName: string,
): { primary: boolean; contextual: boolean } {
  const n = skillName.toLowerCase()
  const primary = area.keywords.length > 0 && includesAny(n, area.keywords)
  const contextual = !primary && Boolean(area.contextualKeywords && includesAny(n, area.contextualKeywords))
  return { primary, contextual }
}

/** True when a project title carries the area's context signal. */
function projectTitleHasContext(area: CapabilityArea, title: string): boolean {
  if (!area.contextKeywords) return false
  return includesAny(title.toLowerCase(), area.contextKeywords)
}

/**
 * Build the row set for one NON-composite area. A row is included when the skill
 * maps to the area directly, OR maps contextually AND the project supplies the
 * area's context (title keyword, or the project also carries a primary skill of
 * this area).
 */
function buildAreaRows(area: CapabilityArea, skills: PassportSkillNode[]): CapabilityEvidenceRow[] {
  // Projects that carry a PRIMARY skill of this area — they unlock contextual
  // skills in the same project even without a title keyword.
  const primaryProjectIds = new Set<string>()
  for (const node of skills) {
    if (skillAreaMatch(area, node.name).primary) {
      for (const row of node.projectEvidence) primaryProjectIds.add(row.projectId)
    }
  }

  const rows: CapabilityEvidenceRow[] = []
  for (const node of skills) {
    const { primary, contextual } = skillAreaMatch(area, node.name)
    if (!primary && !contextual) continue
    for (const row of node.projectEvidence) {
      let include = false
      let isContextual = false
      if (primary) {
        include = true
      } else if (contextual) {
        const hasContext =
          projectTitleHasContext(area, row.projectTitle) || primaryProjectIds.has(row.projectId)
        if (hasContext) {
          include = true
          isContextual = true
        }
      }
      if (!include) continue
      rows.push({
        skillKey: node.key,
        skillName: node.name,
        skillSlug: node.slug,
        projectId: row.projectId,
        projectTitle: row.projectTitle,
        reportPath: row.reportPath,
        publicReportPath: row.publicReportPath,
        reportIsPublic: row.reportIsPublic,
        proofTypes: orderProofTypes(row.evidenceSources),
        skillStatus: row.skillStatus || node.status,
        contextual: isContextual,
      })
    }
  }
  return rows
}

/**
 * Plain-language, honest reason a lower-level skill connects to a role area.
 * Uses only the exact connected project titles + canonical proof-type labels;
 * stays conservative when the link is contextual or proof is thin.
 */
function buildSkillReason(label: string, s: CapabilitySkillSupport): string {
  const where = s.projectTitles.slice(0, 2).join(" and ")
  if (s.contextual) {
    return `Connected to ${label} through ${where}'s role-area context rather than a directly-labelled skill, so the available proof is treated conservatively.`
  }
  if (s.proofTypes.length === 0) {
    return `Connected to ${label} through the project–skill evidence map in ${where}; detailed proof is limited.`
  }
  return `Connected to ${label} because ${s.skillName} supports role-relevant work in ${where}, backed by ${s.proofTypes.join(", ")}.`
}

/** Collapse rows into per-connected-skill supports (strongest skill first). */
function rowsToSkills(label: string, rows: CapabilityEvidenceRow[]): CapabilitySkillSupport[] {
  const bySkill = new Map<string, CapabilitySkillSupport>()
  for (const row of rows) {
    const existing = bySkill.get(row.skillKey)
    if (existing) {
      if (!existing.projectTitles.includes(row.projectTitle)) existing.projectTitles.push(row.projectTitle)
      existing.proofTypes = orderProofTypes([...existing.proofTypes, ...row.proofTypes])
      if (capabilityStatusRank(row.skillStatus) < capabilityStatusRank(existing.status)) {
        existing.status = row.skillStatus
      }
      existing.contextual = existing.contextual && row.contextual
    } else {
      bySkill.set(row.skillKey, {
        skillKey: row.skillKey,
        skillName: row.skillName,
        skillSlug: row.skillSlug,
        status: row.skillStatus,
        projectTitles: [row.projectTitle],
        proofTypes: [...row.proofTypes],
        contextual: row.contextual,
        reason: "",
      })
    }
  }
  const skills = [...bySkill.values()].sort((a, b) => {
    const byStatus = capabilityStatusRank(a.status) - capabilityStatusRank(b.status)
    if (byStatus !== 0) return byStatus
    const byProof = b.proofTypes.length - a.proofTypes.length
    if (byProof !== 0) return byProof
    return a.skillName.localeCompare(b.skillName)
  })
  for (const s of skills) s.reason = buildSkillReason(label, s)
  return skills
}

/** Plain-language, honest reason a project supports a role area. */
function buildProjectReason(label: string, proj: CapabilityProjectSupport): string {
  const skills = proj.skillNames.slice(0, 4).join(", ")
  const proofPhrase = proj.proofTypes.length > 0 ? ` backed by ${proj.proofTypes.join(", ")}` : ""
  const contextNote = proj.contextual
    ? " (linked via this project's role-area context, not a directly-labelled skill)"
    : ""
  return `This project supports ${label} through ${skills}${proofPhrase}${contextNote}.`
}

/** Collapse rows into per-project supports (strongest project first). */
function rowsToProjects(label: string, rows: CapabilityEvidenceRow[]): CapabilityProjectSupport[] {
  const byProject = new Map<string, CapabilityProjectSupport>()
  for (const row of rows) {
    const existing = byProject.get(row.projectId)
    if (existing) {
      if (!existing.skillNames.includes(row.skillName)) existing.skillNames.push(row.skillName)
      if (!existing.skillRefs.some((r) => r.slug === row.skillSlug)) {
        existing.skillRefs.push({ name: row.skillName, slug: row.skillSlug })
      }
      existing.proofTypes = orderProofTypes([...existing.proofTypes, ...row.proofTypes])
      if (capabilityStatusRank(row.skillStatus) < capabilityStatusRank(existing.status)) {
        existing.status = row.skillStatus
      }
      existing.contextual = existing.contextual && row.contextual
    } else {
      byProject.set(row.projectId, {
        projectId: row.projectId,
        projectTitle: row.projectTitle,
        skillNames: [row.skillName],
        skillRefs: [{ name: row.skillName, slug: row.skillSlug }],
        proofTypes: [...row.proofTypes],
        status: row.skillStatus,
        reportPath: row.reportPath,
        publicReportPath: row.publicReportPath,
        reportIsPublic: row.reportIsPublic,
        reason: "",
        contextual: row.contextual,
      })
    }
  }
  const projects = [...byProject.values()].sort((a, b) => {
    const byStatus = capabilityStatusRank(a.status) - capabilityStatusRank(b.status)
    if (byStatus !== 0) return byStatus
    const byProof = b.proofTypes.length - a.proofTypes.length
    if (byProof !== 0) return byProof
    return a.projectTitle.localeCompare(b.projectTitle)
  })
  for (const p of projects) p.reason = buildProjectReason(label, p)
  return projects
}

/**
 * Counts-based evidence sentence — honest, never a readiness/score claim.
 * "Cloud / MLOps is supported by 4 connected skills across 2 projects and 5 proof
 * sources."
 */
function buildSummary(
  label: string,
  skills: CapabilitySkillSupport[],
  projects: CapabilityProjectSupport[],
  proofTypes: string[],
): string {
  if (projects.length === 0) {
    return `${label} has no project-attached evidence yet — it still needs stronger proof mapped to specific projects.`
  }
  const s = `${skills.length} connected ${skills.length === 1 ? "skill" : "skills"}`
  const p = `${projects.length} ${projects.length === 1 ? "project" : "projects"}`
  const pr = `${proofTypes.length} proof ${proofTypes.length === 1 ? "source" : "sources"}`
  return `${label} is supported by ${s} across ${p} and ${pr}.`
}

/** Join titles as "A", "A and B", or "A, B, and C" (max 3 named). */
function joinTitles(titles: string[]): string {
  const shown = titles.slice(0, 3)
  if (shown.length === 0) return ""
  if (shown.length === 1) return shown[0]
  if (shown.length === 2) return `${shown[0]} and ${shown[1]}`
  const extra = titles.length - 3
  const tail = extra > 0 ? `, and ${extra} more` : `, and ${shown[2]}`
  return `${shown[0]}, ${shown[1]}${tail}`
}

/**
 * Build the rich, fact-grounded "why this role area is supported" narrative —
 * 1–2 recruiter-readable paragraphs assembled ONLY from the exact connected
 * skills, project titles, and canonical proof-type labels this aggregate holds.
 * It answers: what the role area means (purpose), which lower-level skills and
 * projects support it, which proof sources back the connection, and why those
 * links together support the high-level area — while staying conservative and
 * never inventing evidence, scores, or a readiness guarantee.
 */
function buildRoleAreaEvidenceNarrative(
  id: string,
  label: string,
  skills: CapabilitySkillSupport[],
  projects: CapabilityProjectSupport[],
  proofTypes: string[],
): string[] {
  const purpose = roleAreaPurpose(id)
  if (projects.length === 0) {
    return [
      `${label} is about ${purpose}. No connected lower-level skills or projects currently support it on this passport — attach related proof to build this role area.`,
    ]
  }

  // Paragraph 1 — the concrete evidence: purpose + which projects + how the
  // strongest project contributes (its exact skills and attached proof sources).
  const projectPhrase = joinTitles(projects.map((p) => p.projectTitle))
  const strongest = projects[0]
  const strongestSkills = strongest.skillNames.slice(0, 4).join(", ")
  const strongestProof =
    strongest.proofTypes.length > 0 ? ` with ${strongest.proofTypes.join(", ")} attached` : ""
  const sentences: string[] = [
    `${label} is about ${purpose}. On this passport it is supported by connected evidence from ${projectPhrase}.`,
    `${strongest.projectTitle} contributes ${strongestSkills}${strongestProof}, which shows role-relevant work across the project rather than an isolated claim.`,
  ]
  // Name a second contributing project when there is one (kept brief).
  if (projects.length > 1) {
    const second = projects[1]
    const secondProof =
      second.proofTypes.length > 0 ? ` (${second.proofTypes.join(", ")})` : ""
    sentences.push(
      `${second.projectTitle} adds further support through ${second.skillNames.slice(0, 3).join(", ")}${secondProof}.`,
    )
  }
  const paragraphOne = sentences.join(" ")

  // Paragraph 2 — why the links hold together as a capability pattern, kept
  // honest: traceable proof chains, qualitative status, conservative on context.
  const namedSkills = skills.slice(0, 4).map((s) => s.skillName)
  const skillList = namedSkills.join(", ")
  const formVerb = namedSkills.length === 1 ? "forms" : "form"
  const contextual = skills.some((s) => s.contextual) || projects.some((p) => p.contextual)
  const contextNote = contextual
    ? " Some links are drawn from related project context rather than a directly-labelled skill, so the claim is kept conservative."
    : ""
  const paragraphTwo =
    `Together, ${skillList || "these connected skills"} ${skillList ? formVerb : "form"} a ${label} capability pattern: each lower-level skill stays traceable to a project and its proof chain instead of a standalone resume keyword. This supports the role area as observed, supporting evidence — every skill and project below links back to its own project report or skill report so a recruiter can inspect it directly.${contextNote}`

  return [paragraphOne, paragraphTwo]
}

/** Ordered evidence-chain node labels: top skills → strongest project → proofs. */
function buildEvidenceChain(
  skills: CapabilitySkillSupport[],
  projects: CapabilityProjectSupport[],
  proofTypes: string[],
): string[] {
  const chain: string[] = []
  for (const s of skills.slice(0, 3)) chain.push(s.skillName)
  if (projects[0]) chain.push(projects[0].projectTitle)
  for (const label of proofTypes.slice(0, 3)) chain.push(label)
  return chain
}

/**
 * Qualitative role-level status label — never "verified" unless proof is real,
 * never a number. Ranges over: Evidence observed, Supporting evidence, Partially
 * demonstrated, Insufficient evidence, Not assessed.
 */
function capabilityStatusLabel(
  rows: CapabilityEvidenceRow[],
  proofTypes: string[],
  projects: CapabilityProjectSupport[],
): string {
  if (projects.length === 0 || rows.length === 0) return "Not assessed"
  const proofCount = proofTypes.length
  if (proofCount === 0) return "Insufficient evidence"
  const bestRank = Math.min(...rows.map((r) => capabilityStatusRank(r.skillStatus)))
  const observedRank = capabilityStatusRank("Evidence observed")
  const partialRank = capabilityStatusRank("Partially demonstrated")
  if (bestRank <= observedRank && proofCount >= 2) return "Evidence observed"
  if (bestRank <= partialRank) return proofCount >= 2 ? "Supporting evidence" : "Partially demonstrated"
  return "Supporting evidence"
}

/** Honest gaps — only true statements derived from the actual proof coverage. */
function buildGaps(
  rows: CapabilityEvidenceRow[],
  proofTypes: string[],
  projects: CapabilityProjectSupport[],
): string[] {
  const gaps: string[] = []
  if (projects.length === 0) {
    gaps.push("No project has attached evidence mapped to this role area yet.")
    return gaps
  }
  if (!proofTypes.includes("GitHub Proof")) {
    gaps.push("No GitHub implementation proof is attached for this capability, so code authorship is not yet demonstrated.")
  }
  if (!proofTypes.includes("Project Defense")) {
    gaps.push("Project Defense is not completed/analyzed for these projects, so the candidate has not defended this capability live.")
  }
  if (proofTypes.includes("Website Proof") && !proofTypes.includes("GitHub Proof")) {
    gaps.push("Website Proof supports observed runtime behavior, not code authorship by itself.")
  }
  if (rows.some((r) => r.contextual)) {
    gaps.push("Some evidence is inferred from related project context rather than a skill explicitly labelled for this role area.")
  }
  return gaps
}

/**
 * Aggregate the evidence-backed Projects↔Skills graph into role-area capability
 * views. NON-composite areas gather their direct + contextual rows; the composite
 * AI Product Engineering area unions rows across AI/ML + product layers and is
 * present only when they span ≥2 distinct layers including AI/ML.
 *
 * `present` areas are the recruiter-facing Role Area options; an area's rows are
 * the exact skill→project relationships to show under that filter, so selecting a
 * role area never surfaces an unrelated project.
 */
export function buildCapabilityAggregates(skills: PassportSkillNode[]): CapabilityAggregate[] {
  // 1 — non-composite areas + remember each area's layer for the composite pass.
  const nonComposite = CAPABILITY_AREAS.filter((a) => !a.composite)
  const areaRows = new Map<string, CapabilityEvidenceRow[]>()
  for (const area of nonComposite) {
    areaRows.set(area.id, buildAreaRows(area, skills))
  }

  const aggregates: CapabilityAggregate[] = nonComposite.map((area) => {
    const rows = areaRows.get(area.id) ?? []
    const projects = rowsToProjects(area.label, rows)
    const skills = rowsToSkills(area.label, rows)
    const skillNames = skills.map((s) => s.skillName)
    const proofTypes = orderProofTypes(rows.flatMap((r) => r.proofTypes))
    const narrative = buildRoleAreaEvidenceNarrative(area.id, area.label, skills, projects, proofTypes)
    return {
      id: area.id,
      label: area.label,
      composite: false,
      present: rows.length > 0,
      rows,
      skills,
      projects,
      skillNames,
      proofTypes,
      statusLabel: capabilityStatusLabel(rows, proofTypes, projects),
      strongest: projects[0] ?? null,
      summary: buildSummary(area.label, skills, projects, proofTypes),
      purpose: roleAreaPurpose(area.id),
      narrative,
      why: narrative[0],
      evidenceChain: buildEvidenceChain(skills, projects, proofTypes),
      gaps: buildGaps(rows, proofTypes, projects),
      layers: area.layer ? [area.layer] : [],
    }
  })

  // 2 — composite AI Product Engineering: union rows from its composeFrom layers.
  if (COMPOSITE_AREA?.composeFrom) {
    const layerOf = new Map(nonComposite.map((a) => [a.id, a.layer]))
    const seen = new Set<string>()
    const rows: CapabilityEvidenceRow[] = []
    const layers = new Set<CapabilityLayer>()
    for (const area of nonComposite) {
      const layer = layerOf.get(area.id)
      if (!layer || !COMPOSITE_AREA.composeFrom.includes(layer)) continue
      for (const row of areaRows.get(area.id) ?? []) {
        const key = `${row.skillKey}::${row.projectId}`
        if (seen.has(key)) continue
        seen.add(key)
        rows.push(row)
        layers.add(layer)
      }
    }
    const projects = rowsToProjects(COMPOSITE_AREA.label, rows)
    const skills = rowsToSkills(COMPOSITE_AREA.label, rows)
    const skillNames = skills.map((s) => s.skillName)
    const proofTypes = orderProofTypes(rows.flatMap((r) => r.proofTypes))
    // Present only with AI/ML at the core AND ≥2 distinct product layers.
    const present = layers.has("ai_ml") && layers.size >= 2
    const layerPhrase = [...layers].map(layerLabel).join(" + ")
    // Rich narrative when present: the shared evidence narrative, prefixed with
    // the multi-layer framing that makes this composite area honest.
    const compositeNarrative = present
      ? (() => {
          const base = buildRoleAreaEvidenceNarrative(
            COMPOSITE_AREA.id,
            COMPOSITE_AREA.label,
            skills,
            projects,
            proofTypes,
          )
          const layerSentence = `This is a composite role area, claimed only because it is backed by multi-layer evidence spanning ${layerPhrase} with AI/ML at the core.`
          return [`${base[0]} ${layerSentence}`, ...base.slice(1)]
        })()
      : [
          `${COMPOSITE_AREA.label} is about ${roleAreaPurpose(COMPOSITE_AREA.id)}. It is only claimed with evidence across AI/ML and at least one product, API, or deployment layer, which is not yet met on this passport.`,
        ]
    aggregates.push({
      id: COMPOSITE_AREA.id,
      label: COMPOSITE_AREA.label,
      composite: true,
      present,
      rows,
      skills,
      projects,
      skillNames,
      proofTypes,
      statusLabel: present ? capabilityStatusLabel(rows, proofTypes, projects) : "Insufficient evidence",
      strongest: projects[0] ?? null,
      summary: present
        ? `${COMPOSITE_AREA.label} is supported by ${skills.length} connected ${skills.length === 1 ? "skill" : "skills"} across ${projects.length} ${projects.length === 1 ? "project" : "projects"} and ${proofTypes.length} proof ${proofTypes.length === 1 ? "source" : "sources"}.`
        : `${COMPOSITE_AREA.label} needs evidence across at least two layers (AI/ML plus product, API, or deployment).`,
      purpose: roleAreaPurpose(COMPOSITE_AREA.id),
      narrative: compositeNarrative,
      why: compositeNarrative[0],
      evidenceChain: buildEvidenceChain(skills, projects, proofTypes),
      gaps: present
        ? buildGaps(rows, proofTypes, projects)
        : ["AI Product Engineering is only claimed with evidence across AI/ML and at least one product/API/deployment layer."],
      layers: [...layers],
    })
  }

  return aggregates
}

function layerLabel(layer: CapabilityLayer): string {
  switch (layer) {
    case "ai_ml":
      return "AI/ML"
    case "backend":
      return "API/backend"
    case "frontend":
      return "product UI"
    case "deployment":
      return "deployment"
    case "data":
      return "data"
    default:
      return "engineering"
  }
}

/** Only the role areas that actually have evidence, in canonical area order. */
export function presentCapabilities(aggregates: CapabilityAggregate[]): CapabilityAggregate[] {
  return aggregates.filter((a) => a.present)
}

/**
 * Set of `${skillKey}::${projectId}` row keys a role area maps. The Role Area
 * filter uses it to keep only the skill→project rows that actually support the
 * area (fail-closed) — an unrelated project never leaks in.
 */
export function capabilityRowKeys(aggregate: CapabilityAggregate | null): Set<string> {
  const keys = new Set<string>()
  if (!aggregate) return keys
  for (const row of aggregate.rows) keys.add(`${row.skillKey}::${row.projectId}`)
  return keys
}

// Re-exported for callers that only need the row shape name.
export type { SkillProjectEvidence }
