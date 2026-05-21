/**
 * evidence-sources.ts — Phase J4B
 * Source type catalog, YouTube timestamp utilities, and extraction status
 * helpers for the multi-source evidence collection system.
 */

// ── Source type catalog ───────────────────────────────────────────────────────

export type EvidenceSourceType =
  | "github_repository"
  | "deployed_website"
  | "linkedin_post"
  | "youtube_demo"
  | "google_drive_document"
  | "pdf_report"
  | "certificate"
  | "portfolio"
  | "manual_entry"
  | "other_link"

/** Maps a UI EvidenceSourceType to the evidence_type string stored in the DB. */
export function sourceTypeToEvidenceType(sourceType: EvidenceSourceType): string {
  const map: Record<EvidenceSourceType, string> = {
    github_repository: "github repository",
    deployed_website: "deployed website",
    linkedin_post: "linkedin_post",
    youtube_demo: "youtube_demo",
    google_drive_document: "google_drive_document",
    pdf_report: "pdf_report",
    certificate: "certificate",
    portfolio: "portfolio",
    manual_entry: "manual_entry",
    other_link: "other_link",
  }
  return map[sourceType]
}

/** Badge label for source chips and Skill Proof Center. */
export function sourceTypeToBadgeLabel(sourceType: EvidenceSourceType): string {
  const map: Record<EvidenceSourceType, string> = {
    github_repository: "GitHub",
    deployed_website: "Website",
    linkedin_post: "LinkedIn",
    youtube_demo: "YouTube",
    google_drive_document: "Google Drive",
    pdf_report: "PDF / Report",
    certificate: "Certificate",
    portfolio: "Portfolio",
    manual_entry: "Manual",
    other_link: "Other",
  }
  return map[sourceType]
}

/** Short description shown under source type cards in the selector. */
export function sourceTypeToDescription(sourceType: EvidenceSourceType): string {
  const map: Record<EvidenceSourceType, string> = {
    github_repository: "Code file, line range, and repo URL",
    deployed_website: "Live deployed app with AI verification",
    linkedin_post: "Public LinkedIn post or profile link",
    youtube_demo: "Demo video with optional timestamp range",
    google_drive_document: "Google Doc, Sheet, or Slides — shareable link",
    pdf_report: "PDF, research paper, or project report",
    certificate: "Certificate URL, issuer, and credential ID",
    portfolio: "Behance, Dribbble, personal portfolio, or project page",
    manual_entry: "Free-text description — no external URL required",
    other_link: "Any other public resource or proof link",
  }
  return map[sourceType]
}

/** Emoji icon for source type selector cards. */
export function sourceTypeToIcon(sourceType: EvidenceSourceType): string {
  const map: Record<EvidenceSourceType, string> = {
    github_repository: "⌨",
    deployed_website: "🌐",
    linkedin_post: "💼",
    youtube_demo: "▶",
    google_drive_document: "📄",
    pdf_report: "📑",
    certificate: "🏅",
    portfolio: "🎨",
    manual_entry: "✍",
    other_link: "🔗",
  }
  return map[sourceType]
}

// ── Extraction status ─────────────────────────────────────────────────────────

export type ExtractionStatus = "active" | "queued" | "future"

export type EvidenceExtractionStatus = {
  sourceType: EvidenceSourceType
  status: ExtractionStatus
  label: string
  message: string
}

/** Current AI extraction readiness for a given source type. */
export function getExtractionStatus(sourceType: EvidenceSourceType): EvidenceExtractionStatus {
  if (sourceType === "github_repository") {
    return {
      sourceType, status: "active", label: "Active",
      message: "GitHub scanning is live. Scan your GitHub profile to extract proof automatically.",
    }
  }
  if (sourceType === "deployed_website") {
    return {
      sourceType, status: "active", label: "Active",
      message: "Website verification is live. Submit a live website URL to run AI verification.",
    }
  }
  const queued: EvidenceSourceType[] = ["linkedin_post", "youtube_demo", "google_drive_document", "pdf_report"]
  if (queued.includes(sourceType)) {
    return {
      sourceType, status: "queued", label: "AI Extraction Coming Soon",
      message: "You can save this link now. AI extraction for this source will be added in an upcoming phase.",
    }
  }
  return {
    sourceType, status: "future", label: "Save Now",
    message: "Save this evidence now. VeriBridge will organize it in your Skill Proof Center.",
  }
}

// ── YouTube timestamp utilities ───────────────────────────────────────────────

/**
 * Parses a timestamp string to total seconds.
 * Accepts: "05:12", "5:12", "00:05:12", "312", "312s", "312 seconds"
 */
export function parseTimestampToSeconds(ts: string): number | null {
  const cleaned = ts.trim().replace(/\s+seconds?$/i, "").replace(/s$/i, "")

  const colonParts = cleaned.split(":").map((p) => p.trim())
  if (colonParts.length === 2) {
    const [min, sec] = colonParts.map((p) => parseInt(p, 10))
    if (!isNaN(min) && !isNaN(sec)) return min * 60 + sec
  }
  if (colonParts.length === 3) {
    const [hr, min, sec] = colonParts.map((p) => parseInt(p, 10))
    if (!isNaN(hr) && !isNaN(min) && !isNaN(sec)) return hr * 3600 + min * 60 + sec
  }

  const num = parseInt(cleaned, 10)
  if (!isNaN(num) && num >= 0) return num
  return null
}

/** Formats total seconds as "MM:SS" or "H:MM:SS" for display. */
export function formatSecondsAsTimestamp(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  const mm = String(m).padStart(2, "0")
  const ss = String(s).padStart(2, "0")
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/** Extracts video ID from a YouTube URL. Returns null if not a YouTube URL. */
export function extractYouTubeVideoId(url: string): string | null {
  try {
    const u = new URL(url)
    if (u.hostname === "youtu.be") return u.pathname.slice(1).split("?")[0] ?? null
    if (u.hostname.includes("youtube.com")) {
      const v = u.searchParams.get("v")
      if (v) return v
      const parts = u.pathname.split("/").filter(Boolean)
      if (parts[0] === "shorts" && parts[1]) return parts[1]
    }
  } catch { /* not a URL */ }
  return null
}

/**
 * Returns a YouTube URL with `t=Xs` set to startSeconds.
 * Preserves the existing URL, video ID, and any other params.
 */
export function buildYouTubeTimestampUrl(videoUrl: string, startSeconds: number): string {
  try {
    const u = new URL(videoUrl)
    if (u.hostname === "youtu.be" || u.hostname.includes("youtube.com")) {
      u.searchParams.set("t", `${startSeconds}s`)
      return u.toString()
    }
  } catch { /* fallthrough */ }
  const sep = videoUrl.includes("?") ? "&" : "?"
  return `${videoUrl}${sep}t=${startSeconds}s`
}
