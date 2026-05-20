"use client";

export type ProofVerificationDisplayStatus =
  | "verified"
  | "supported_with_review"
  | "partially_supported"
  | "not_verified"
  | "pending_analysis";

export type ProofVerificationAssessment = {
  available?: boolean;
  baseEvidenceStatus?: string | null;
  semanticStatus?: string | null;
  reportStatus?: string | null;
  browserStatus?: string | null;
  staticStatus?: string | null;
  capabilityMatchStatus?: string | null;
  expectedOutputMatchStatus?: string | null;
  missingCriticalRequirements?: boolean;
  blocksFullVerification?: boolean;
  expectedOutputBlocksVerification?: boolean;
  supportingEvidence?: boolean;
};

export type ProofVerificationReconciliation = {
  available: boolean;
  displayStatus: ProofVerificationDisplayStatus;
  confidenceBand: "high" | "medium" | "low";
  shortDisplayLabel: string;
  studentFacingMessage: string;
  recruiterFacingMessage: string;
  reviewRecommended: boolean;
  notes?: string | null;
  technicalStatuses: {
    baseEvidenceStatus?: string | null;
    semanticStatus?: string | null;
    reportStatus?: string | null;
    browserStatus?: string | null;
    staticStatus?: string | null;
    capabilityMatchStatus?: string | null;
    expectedOutputMatchStatus?: string | null;
  };
};

const NEGATIVE_STATUSES = new Set([
  "not_verified",
  "skill_usage_not_found",
  "rejected",
  "browser_failed",
  "execution_error",
  "execution_timeout",
  "blocked_by_login",
  "unsupported",
  "unsupported_plan",
  "evaluation_error",
  "report_error",
]);

const REVIEW_STATUSES = new Set([
  "needs_human_review",
  "needs_more_detail",
  "partially_verified",
  "browser_partially_verified",
  "partial_verification",
  "weak_match",
  "moderate_semantic_match",
]);

export function reconcileProofVerificationDisplayState(
  assessment: ProofVerificationAssessment
): ProofVerificationReconciliation {
  const available = assessment.available !== false;
  const statuses = {
    baseEvidenceStatus: normalizeStatus(assessment.baseEvidenceStatus),
    semanticStatus: normalizeStatus(assessment.semanticStatus),
    reportStatus: normalizeStatus(assessment.reportStatus),
    browserStatus: normalizeStatus(assessment.browserStatus),
    staticStatus: normalizeStatus(assessment.staticStatus),
    capabilityMatchStatus: normalizeStatus(assessment.capabilityMatchStatus),
    expectedOutputMatchStatus: normalizeStatus(assessment.expectedOutputMatchStatus),
  };

  if (!available) {
    return buildResult("pending_analysis", "low", "Pending analysis", "Proof analysis is still pending.", "Proof analysis is still pending.", true, "The proof pipeline has not produced enough structured evidence yet.", statuses);
  }

  if (hasExplicitNegative(assessment, statuses)) {
    return buildResult("not_verified", "low", "Not verified", "The selected evidence does not currently support the student's claim.", "The selected evidence does not currently support the student's claim.", false, "A contradiction, critical missing capability, or blocking verification failure was detected.", statuses);
  }

  const supportLevel = determineSupportLevel(assessment, statuses);
  if (supportLevel === "strong") {
    return buildResult("verified", "high", "Verified", "The proof is strongly supported by the automated evidence.", "The proof is strongly supported by the automated evidence.", false, "The semantic and capability signals align without a material warning.", statuses);
  }
  if (supportLevel === "review") {
    return buildResult(
      "supported_with_review",
      "medium",
      "Supported with review",
      "Relevant evidence was found, but some claim details still benefit from review.",
      "Relevant evidence was found, but some claim details still benefit from review.",
      true,
      "The evidence is materially supportive, but one or more verifier layers remained cautious.",
      statuses
    );
  }
  if (supportLevel === "partial") {
    return buildResult(
      "partially_supported",
      "medium",
      "Partially supported",
      "Only part of the claim is supported by the current evidence.",
      "Only part of the claim is supported by the current evidence.",
      true,
      "Some capabilities or outputs were confirmed, but the full claim was not.",
      statuses
    );
  }

  return buildResult("pending_analysis", "low", "Pending analysis", "Proof analysis is still in progress.", "Proof analysis is still in progress.", true, "The available signals are sparse or incomplete.", statuses);
}

export function formatProofDisplayLabel(displayStatus: ProofVerificationDisplayStatus, audience: "student" | "recruiter" = "student"): string {
  if (audience === "recruiter") {
    return {
      verified: "Verified",
      supported_with_review: "Supported with review",
      partially_supported: "Partially supported",
      not_verified: "Not verified",
      pending_analysis: "Pending analysis",
    }[displayStatus];
  }
  return {
    verified: "Evidence accepted",
    supported_with_review: "Supported with review",
    partially_supported: "Partially supported",
    not_verified: "Not verified",
    pending_analysis: "Pending analysis",
  }[displayStatus];
}

export function formatBaseEvidenceAcceptanceLabel(status: string | null | undefined): string {
  const normalized = normalizeStatus(status);
  if (normalized === "verified") return "Evidence accepted";
  if (normalized === "skill_usage_not_found" || normalized === "not_verified" || normalized === "rejected") return "Not verified";
  if (normalized === "needs_review") return "Review recommended";
  return "Pending analysis";
}

function determineSupportLevel(assessment: ProofVerificationAssessment, statuses: Record<string, string | null | undefined>): "strong" | "review" | "partial" | "pending" {
  const semanticStatus = statuses.semanticStatus;
  const reportStatus = statuses.reportStatus;
  const browserStatus = statuses.browserStatus;
  const staticStatus = statuses.staticStatus;
  const capabilityMatchStatus = statuses.capabilityMatchStatus;
  const expectedOutputMatchStatus = statuses.expectedOutputMatchStatus;

  if ((semanticStatus === "verified" || reportStatus === "verified") && capabilityMatchStatus !== "capability_mismatch" && expectedOutputMatchStatus !== "low_expected_output_match") {
    if (semanticStatus === "verified" && reportStatus === "verified" && !hasAnyReviewWarning(browserStatus, staticStatus, assessment)) {
      return "strong";
    }
    if (hasAnyReviewWarning(browserStatus, staticStatus, assessment)) {
      return "review";
    }
    return "strong";
  }

  if (semanticStatus === "partially_verified" || reportStatus === "partially_verified") return "partial";
  if (semanticStatus === "needs_human_review" || reportStatus === "needs_human_review") {
    return hasSupportingEvidence(assessment, statuses) ? "review" : "partial";
  }
  if (browserStatus === "browser_partially_verified" || staticStatus === "partial_verification") {
    return hasSupportingEvidence(assessment, statuses) ? "partial" : "pending";
  }
  if (hasSupportingEvidence(assessment, statuses)) return "partial";
  return "pending";
}

function hasSupportingEvidence(
  assessment: ProofVerificationAssessment,
  statuses: Record<string, string | null | undefined>
): boolean {
  return Boolean(
    assessment.supportingEvidence ||
      statuses.semanticStatus === "verified" ||
      statuses.semanticStatus === "partially_verified" ||
      statuses.semanticStatus === "needs_human_review" ||
      statuses.reportStatus === "verified" ||
      statuses.reportStatus === "partially_verified" ||
      statuses.reportStatus === "needs_human_review" ||
      statuses.browserStatus === "browser_verified" ||
      statuses.browserStatus === "browser_partially_verified" ||
      statuses.staticStatus === "static_verified" ||
      statuses.staticStatus === "partial_verification" ||
      statuses.capabilityMatchStatus === "strong_capability_match" ||
      statuses.capabilityMatchStatus === "partial_capability_match" ||
      statuses.expectedOutputMatchStatus === "strong_expected_output_match" ||
      statuses.expectedOutputMatchStatus === "moderate_expected_output_match" ||
      statuses.expectedOutputMatchStatus === "weak_expected_output_match"
  );
}

function hasAnyReviewWarning(
  browserStatus: string | null | undefined,
  staticStatus: string | null | undefined,
  assessment: ProofVerificationAssessment
): boolean {
  const browserReview = browserStatus ? REVIEW_STATUSES.has(browserStatus) : false;
  const staticReview = staticStatus ? REVIEW_STATUSES.has(staticStatus) : false;
  return Boolean(
    browserReview ||
      staticReview ||
      assessment.capabilityMatchStatus === "partial_capability_match" ||
      assessment.expectedOutputMatchStatus === "moderate_expected_output_match" ||
      assessment.expectedOutputMatchStatus === "weak_expected_output_match" ||
      assessment.expectedOutputBlocksVerification
  );
}

function hasExplicitNegative(
  assessment: ProofVerificationAssessment,
  statuses: Record<string, string | null | undefined>
): boolean {
  if (assessment.blocksFullVerification) return true;
  if (assessment.missingCriticalRequirements) return true;
  if (statuses.capabilityMatchStatus === "capability_mismatch") return true;
  if (statuses.expectedOutputMatchStatus === "low_expected_output_match") return true;
  if (statuses.semanticStatus === "not_verified" || statuses.semanticStatus === "evaluation_error") return true;
  if (statuses.reportStatus === "not_verified" || statuses.reportStatus === "report_error") return true;
  if (statuses.browserStatus && NEGATIVE_STATUSES.has(statuses.browserStatus)) return true;
  if (statuses.staticStatus && NEGATIVE_STATUSES.has(statuses.staticStatus)) return true;
  if (statuses.capabilityMatchStatus === "weak_capability_match" && !hasSupportingEvidence(assessment, statuses)) return true;
  return false;
}

function buildResult(
  displayStatus: ProofVerificationDisplayStatus,
  confidenceBand: "high" | "medium" | "low",
  shortDisplayLabel: string,
  studentFacingMessage: string,
  recruiterFacingMessage: string,
  reviewRecommended: boolean,
  notes: string | undefined,
  technicalStatuses: ProofVerificationReconciliation["technicalStatuses"]
): ProofVerificationReconciliation {
  return {
    available: true,
    displayStatus,
    confidenceBand,
    shortDisplayLabel,
    studentFacingMessage,
    recruiterFacingMessage,
    reviewRecommended,
    notes,
    technicalStatuses,
  };
}

function normalizeStatus(value: string | null | undefined): string | null {
  const trimmed = typeof value === "string" ? value.trim() : ""
  return trimmed || null
}
