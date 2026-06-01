/**
 * Live Proof Feedback Engine — Chrome extension side.
 *
 * Pure function — no I/O, no Qwen, deterministic.
 * Mirrors the logic in app/services/live_feedback_engine.py.
 *
 * Takes accumulated VisibleEvidenceEvents + session metadata and returns a
 * LiveCoachState that the popup renders directly.
 */

import type { VisibleEvidenceEvent } from "./types"

// ── Output types ──────────────────────────────────────────────────────────────

export type SupportLevel = "missing" | "partial" | "likely"

export interface SkillSupport {
  skill: string
  support_level: SupportLevel
  evidence_source: string
  short_reason: string
}

export interface EvidenceChecklist {
  website_loaded: boolean
  dom_text_seen: boolean
  interaction_seen: boolean
  form_input_seen: boolean
  output_or_result_seen: boolean
  chart_or_visual_seen: boolean
  code_or_repo_seen: boolean
  github_seen: boolean
  sensitive_warning: boolean
}

export interface LiveCoachState {
  live_score: number
  checklist: EvidenceChecklist
  claimed_skill_support: SkillSupport[]
  suggestions: string[]
  sensitive_warning: boolean
}

// ── Skill category patterns ───────────────────────────────────────────────────

type SkillCategory =
  | "github_open_source"
  | "data_visualization"
  | "ml_ai"
  | "code_software"
  | "document_pdf"
  | "video_media"
  | "engineering_design"
  | "business_finance"
  | "generic"

const SKILL_PATTERNS: Array<[SkillCategory, RegExp]> = [
  ["github_open_source",  /\b(open[\s_-]?source|github|repository|repo|git)\b/i],
  ["data_visualization",  /\b(data[\s_-]?vis(ualization)?|chart|dashboard|plot(ting)?|graph(ing)?|d3|vega|plotly|tableau|observable|matplotlib|seaborn|bokeh|bi|business[\s_-]?intelligence|analytics[\s_-]?dashboard)\b/i],
  ["ml_ai",               /\b(machine[\s_-]?learning|ml|deep[\s_-]?learning|ai|tensorflow|pytorch|keras|scikit|sklearn|model|neural|nlp|computer[\s_-]?vision|object[\s_-]?detection|classification|regression|clustering|transformer|llm|generative)\b/i],
  ["code_software",       /\b(javascript|typescript|python|java|c\+\+|c#|go|rust|ruby|php|swift|kotlin|coding|programming|software|algorithm|api|backend|frontend|fullstack|react|vue|angular|next\.?js|node|django|flask|fastapi|spring|rails|html|css|web[\s_-]?dev(elopment)?)\b/i],
  ["document_pdf",        /\b(document|pdf|report|spreadsheet|excel|word|presentation|slide)\b/i],
  ["video_media",         /\b(video|audio|media|stream(ing)?|player|recording)\b/i],
  ["engineering_design",  /\b(cad|solidworks|autocad|fusion|design|mechanical|electrical|circuit|schematic|simulation|finite[\s_-]?element|ansys|matlab)\b/i],
  ["business_finance",    /\b(finance|financial|accounting|trading|portfolio|stock|investment|economics|budget|forecast|erp|crm|salesforce)\b/i],
]

const RESULT_RE = /\b(prediction|result|output|score|confidence|probability|risk|detected|label|class|summary|answer|response|route|recommendation|generated|analysis|accuracy|precision|recall|f1|loss|error|total|count|mean|average|percentage|trend)\b/i
const CHART_TEXT_RE = /\b(chart|graph|plot|axis|legend|tooltip|bar|line|pie|scatter|histogram|heatmap|treemap|sunburst|choropleth|dashboard)\b/i
const CODE_TEXT_RE = /\b(def |class |function |import |require|const |let |var |return |if\s*\(|for\s*\(|while\s*\(|console\.log|print\(|github\.com|commit|branch|pull[\s_-]?request|\.py|\.js|\.ts|\.java)\b/i
const GITHUB_URL_RE = /github\.com\/[\w\-]+\/[\w\-]/i
const SENSITIVE_RE = /password|passcode|pass\b|token|secret|api[\s_\-]?key|apikey|access[\s_\-]?key|private[\s_\-]?key|bearer|auth(?:entication|orization|token)?|credential|ssn|social[\s_\-]?security|credit[\s_\-]?card|card[\s_\-]?number|cvv|cvc|expir|bank|routing|account[\s_\-]?number/i

function classifySkill(skill: string): SkillCategory {
  for (const [cat, pattern] of SKILL_PATTERNS) {
    if (pattern.test(skill)) return cat
  }
  return "generic"
}

// ── Checklist ─────────────────────────────────────────────────────────────────

function buildChecklist(
  events: VisibleEvidenceEvent[],
  sensitiveWarningSeen: boolean,
): EvidenceChecklist {
  const allText = events.flatMap(e => e.visible_text_blocks).join(" ")
  const resultText = events.flatMap(e => e.result_like_blocks).join(" ")
  const allUrls = events.map(e => e.url).join(" ")

  const clickCount = events.filter(e => e.event_type === "click").length
  const inputCount = events.filter(e => e.event_type === "input_change").length
  const formCount  = events.filter(e => e.event_type === "form_submit").length
  const maxCanvas  = Math.max(0, ...events.map(e => e.canvas_count ?? 0))
  const maxSvg     = Math.max(0, ...events.map(e => e.svg_count ?? 0))

  const website_loaded       = events.some(e => e.event_type === "page_load")
  const dom_text_seen        = events.some(e => e.visible_text_blocks.length > 0)
  const interaction_seen     = clickCount > 0
  const form_input_seen      = inputCount > 0 || formCount > 0
  const output_or_result_seen =
    events.some(e => e.event_type === "result_detected") ||
    events.some(e => e.result_like_blocks.length > 0) ||
    RESULT_RE.test(resultText)
  const chart_or_visual_seen = maxCanvas > 0 || maxSvg > 0 || CHART_TEXT_RE.test(allText)
  const code_or_repo_seen    = CODE_TEXT_RE.test(allText)
  const github_seen          =
    GITHUB_URL_RE.test(allUrls) ||
    events.some(e => GITHUB_URL_RE.test(e.url))

  // Check visible text blocks for sensitive content (content.ts sanitizes values but labels remain)
  const sensitive_warning    = sensitiveWarningSeen || SENSITIVE_RE.test(allText)

  return {
    website_loaded,
    dom_text_seen,
    interaction_seen,
    form_input_seen,
    output_or_result_seen,
    chart_or_visual_seen,
    code_or_repo_seen,
    github_seen,
    sensitive_warning,
  }
}

// ── Score ──────────────────────────────────────────────────────────────────────

const SCORE_WEIGHTS: Record<keyof Omit<EvidenceChecklist, "sensitive_warning">, number> = {
  website_loaded:          15,
  dom_text_seen:           15,
  interaction_seen:        15,
  form_input_seen:         10,
  output_or_result_seen:   15,
  chart_or_visual_seen:    10,
  code_or_repo_seen:       10,
  github_seen:             10,
}

function computeScore(c: EvidenceChecklist): number {
  let total = 0
  for (const [field, weight] of Object.entries(SCORE_WEIGHTS)) {
    if (c[field as keyof typeof SCORE_WEIGHTS]) total += weight
  }
  return Math.min(total, 100)
}

// ── Skill support ─────────────────────────────────────────────────────────────

function skillSupport(skill: string, c: EvidenceChecklist): SkillSupport {
  const cat = classifySkill(skill)

  let level: SupportLevel
  let evidence_source: string
  let short_reason: string

  switch (cat) {
    case "github_open_source":
      if (c.github_seen) {
        level = "likely"; evidence_source = "github_url"
        short_reason = "GitHub URL visited — repository evidence captured"
      } else if (c.code_or_repo_seen) {
        level = "partial"; evidence_source = "code_text"
        short_reason = "Code text seen — visit GitHub for stronger evidence"
      } else {
        level = "missing"; evidence_source = "none"
        short_reason = "No GitHub URL or code seen yet"
      }
      break

    case "data_visualization":
      if (c.chart_or_visual_seen && c.interaction_seen) {
        level = "likely"; evidence_source = "chart_and_interaction"
        short_reason = "Chart/visual detected and interaction recorded"
      } else if (c.chart_or_visual_seen) {
        level = "partial"; evidence_source = "chart_seen"
        short_reason = "Chart/visual detected — interact with a control for stronger evidence"
      } else if (c.output_or_result_seen) {
        level = "partial"; evidence_source = "output_text"
        short_reason = "Output text seen — show the chart clearly"
      } else {
        level = "missing"; evidence_source = "none"
        short_reason = "No chart, canvas, or visualization detected yet"
      }
      break

    case "ml_ai":
      if (c.output_or_result_seen && c.interaction_seen) {
        level = "likely"; evidence_source = "result_and_interaction"
        short_reason = "Result/output detected with user interaction"
      } else if (c.output_or_result_seen) {
        level = "partial"; evidence_source = "result_text"
        short_reason = "Result text seen — interact with the model for stronger evidence"
      } else {
        level = "missing"; evidence_source = "none"
        short_reason = "No model output or prediction result detected yet"
      }
      break

    case "code_software":
      if (c.code_or_repo_seen && c.interaction_seen) {
        level = "likely"; evidence_source = "code_and_interaction"
        short_reason = "Code text seen with user interaction"
      } else if (c.github_seen) {
        level = "likely"; evidence_source = "github"
        short_reason = "GitHub repository evidence captured"
      } else if (c.code_or_repo_seen) {
        level = "partial"; evidence_source = "code_text"
        short_reason = "Code text seen — show more code or add GitHub URL"
      } else if (c.interaction_seen && c.output_or_result_seen) {
        level = "partial"; evidence_source = "app_interaction"
        short_reason = "App interaction and output seen — show code for stronger evidence"
      } else {
        level = "missing"; evidence_source = "none"
        short_reason = "No code, GitHub, or running app output detected yet"
      }
      break

    default:
      if (c.interaction_seen && c.output_or_result_seen) {
        level = "likely"; evidence_source = "interaction_and_output"
        short_reason = "App interaction and output captured"
      } else if (c.interaction_seen) {
        level = "partial"; evidence_source = "interaction"
        short_reason = "Interaction seen — show the result/output clearly"
      } else if (c.dom_text_seen) {
        level = "partial"; evidence_source = "dom_text"
        short_reason = "Page text captured — interact with the app"
      } else {
        level = "missing"; evidence_source = "none"
        short_reason = "No app interaction detected yet"
      }
  }

  return { skill, support_level: level, evidence_source, short_reason }
}

// ── Suggestions ────────────────────────────────────────────────────────────────

function buildSuggestions(
  c: EvidenceChecklist,
  skillSupports: SkillSupport[],
): string[] {
  const suggestions: string[] = []

  if (c.sensitive_warning) {
    suggestions.push("Avoid showing API keys, tokens, passwords, SSNs, or payment info.")
  }
  if (suggestions.length >= 3) return suggestions

  if (!c.output_or_result_seen && c.interaction_seen) {
    suggestions.push("Show the result or output area clearly after running the app.")
  }
  if (suggestions.length >= 3) return suggestions

  if (!c.interaction_seen && c.website_loaded) {
    suggestions.push("Good start. Now interact with the app — click a control or run a task.")
  }
  if (suggestions.length >= 3) return suggestions

  for (const support of skillSupports) {
    if (support.support_level !== "missing") continue
    const cat = classifySkill(support.skill)
    if (cat === "github_open_source") {
      suggestions.push(`For '${support.skill}': visit your GitHub repository or provide a repo URL.`)
    } else if (cat === "data_visualization") {
      suggestions.push(`For '${support.skill}': show the chart or visualization clearly and interact with one control.`)
    } else if (cat === "ml_ai") {
      suggestions.push(`For '${support.skill}': run the model and show the prediction or output clearly.`)
    } else if (cat === "code_software") {
      suggestions.push(`For '${support.skill}': show code in the browser or add a GitHub repository URL.`)
    } else {
      suggestions.push(`For '${support.skill}': interact with the app and show its output.`)
    }
    if (suggestions.length >= 3) break
  }
  if (suggestions.length >= 3) return suggestions

  for (const support of skillSupports) {
    if (support.support_level !== "partial") continue
    const cat = classifySkill(support.skill)
    if (cat === "data_visualization" && !c.github_seen) {
      suggestions.push(`For '${support.skill}': add a GitHub or code repository link for stronger evidence.`)
    } else if (cat === "code_software" && !c.github_seen) {
      suggestions.push(`For '${support.skill}': visit GitHub to add repository evidence.`)
    } else if (cat === "ml_ai" && !c.interaction_seen) {
      suggestions.push(`For '${support.skill}': interact with the model (upload data, run inference).`)
    }
    if (suggestions.length >= 3) break
  }

  if (suggestions.length === 0 && c.interaction_seen && c.output_or_result_seen) {
    suggestions.push("Good evidence captured! Consider showing more of the app's output.")
  }

  return suggestions.slice(0, 3)
}

// ── Main export ────────────────────────────────────────────────────────────────

export function computeLiveCoach(
  claimedSkills: string[],
  events: VisibleEvidenceEvent[],
  sensitiveWarningSeen = false,
): LiveCoachState {
  const checklist = buildChecklist(events, sensitiveWarningSeen)
  const live_score = computeScore(checklist)
  const claimed_skill_support = claimedSkills.map(s => skillSupport(s, checklist))
  const suggestions = buildSuggestions(checklist, claimed_skill_support)

  return {
    live_score,
    checklist,
    claimed_skill_support,
    suggestions,
    sensitive_warning: checklist.sensitive_warning,
  }
}
