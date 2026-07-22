/**
 * Coherent Project Defense overall score — display guard.
 *
 * Mirrors the backend rubric (apps/api/app/services/
 * project_defense_analysis_service.py — coherent_overall_defense_score):
 *
 *   overall = 20 (length) + 20 (skills) + 10 (limitations)
 *           + 20 × consistency/100 + 15 × ownership/100 + 15 × depth/100
 *           − penalties, clamped to [0, 100]
 *
 * Legacy persisted rows (pre-proportional rubric) can carry an overall of 100
 * beside components of 60/65 — the historical "OVERALL 100/100 vs components
 * 60/65/75" contradiction. Those rows are never mutated; the backend serves a
 * coherently derived value, and this guard applies the same cap at render time
 * so a stale or legacy payload can never display an overall its own components
 * contradict. For coherent payloads this is the identity.
 */

const LENGTH_WEIGHT = 20
const SKILLS_WEIGHT = 20
const LIMITATIONS_WEIGHT = 10
const CONSISTENCY_WEIGHT = 20
const OWNERSHIP_WEIGHT = 15
const TECH_DEPTH_WEIGHT = 15

type DefenseScoreComponents = {
  overall_defense_score: number
  consistency_with_evidence_score: number
  ownership_signal_score: number
  technical_depth_score: number
}

function clampComponent(value: number): number {
  return Math.min(100, Math.max(0, Math.round(value || 0)))
}

/**
 * The maximum overall the rubric allows for the given component scores
 * (binary criteria assumed fully met, no penalties — the most generous
 * coherent interpretation).
 */
export function maxCoherentOverallDefenseScore(
  analysis: Pick<
    DefenseScoreComponents,
    "consistency_with_evidence_score" | "ownership_signal_score" | "technical_depth_score"
  >,
): number {
  return Math.min(
    100,
    LENGTH_WEIGHT +
      SKILLS_WEIGHT +
      LIMITATIONS_WEIGHT +
      Math.round((CONSISTENCY_WEIGHT * clampComponent(analysis.consistency_with_evidence_score)) / 100) +
      Math.round((OWNERSHIP_WEIGHT * clampComponent(analysis.ownership_signal_score)) / 100) +
      Math.round((TECH_DEPTH_WEIGHT * clampComponent(analysis.technical_depth_score)) / 100),
  )
}

/**
 * The overall defense score safe to display beside the component scores:
 * the stored overall capped at what the components can support.
 */
export function coherentOverallDefenseScore(analysis: DefenseScoreComponents): number {
  const overall = Math.max(0, Math.round(analysis.overall_defense_score || 0))
  return Math.min(overall, maxCoherentOverallDefenseScore(analysis))
}
