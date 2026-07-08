"use client"

import type { CSSProperties, ReactNode } from "react"

import type { PassportCardCapability, PassportCardModel } from "@/lib/passport-card"

/** Qualitative status → dot colour (never a numeric score). */
const STATUS_DOT: Record<string, string> = {
  Demonstrated: "#10b981",
  "Evidence observed": "#10b981",
  "Partially demonstrated": "#d97706",
  "Supporting evidence": "#0ea5e9",
  "Needs review": "#f43f5e",
  "Not assessed": "#94a3b8",
}

/** Light-mode palette for the card face (kept local so the card stays portable). */
const C = {
  ink: "#0a0e1a",
  inkSoft: "#1f2a44",
  muted: "#6b7280",
  faint: "#9aa3b2",
  line: "#e6e8ef",
  lineSoft: "#eef0f6",
  paper: "#ffffff",
  wash: "#f8fafc",
  indigo: "#4f46e5",
  indigoDeep: "#3730a3",
  indigoSoft: "#eef2ff",
  indigoLine: "#dfe4ff",
  emerald: "#059669",
  emeraldSoft: "#ecfdf5",
  emeraldLine: "#a7f3d0",
} as const

/**
 * The Verified Passport Card — a clean, premium, light-mode digital credential
 * (professional verified-talent-card style) shared by the private preview and the
 * public `/card/[slug]` route. It answers a recruiter's five-second question —
 * who is this, what role areas can they apply for, what proof backs that, is the
 * profile verified, how do I open the full Passport — WITHOUT being a report: no
 * featured-project list, no raw evidence, no scores.
 *
 * Deliberately recruiter-facing and honest:
 *  - NO QR / barcode / scan box on the card face (a QR belongs only in the
 *    Passport Beam / QR modal, never on the credential itself);
 *  - proof breadth is shown as a quiet, neutral "Proof sources" row (present
 *    sources only) plus one evidence line — proof-backed language, never
 *    "certified expert", never a numeric confidence score.
 *
 * Role chips deep-link to real, evidence-backed skills (same-page for the private
 * preview via {@link onCapabilityClick}; cross-page for the public card via
 * {@link capabilityHref}). The student can choose which role areas appear via the
 * private "Customize Passport Card" selector, passed here as {@link capabilities};
 * when omitted the card shows the model's default top role areas.
 */
export function PassportCard({
  model,
  variant,
  capabilities,
  onCapabilityClick,
  capabilityHref,
  footer,
}: {
  model: PassportCardModel
  variant: "private" | "public"
  /**
   * Role areas to render on the face (already capped/ordered by the caller). When
   * omitted the card falls back to `model.capabilities` (the default top areas).
   */
  capabilities?: PassportCardCapability[]
  /** Same-page role-chip selection (private preview → filter the evidence map). */
  onCapabilityClick?: (cap: PassportCardCapability) => void
  /** Cross-page role-chip deep link (public card → full Passport skill evidence). */
  capabilityHref?: (cap: PassportCardCapability) => string
  /** CTAs / recruiter-safe note rendered below the card body. */
  footer?: ReactNode
}) {
  const isLive = model.isPublished
  const initials = model.initials || "★"
  const photo = model.profileImageUrl
  const portrait = 84
  const radius = 20
  const shownCapabilities = capabilities ?? model.capabilities
  const presentProof = model.proofCoverage.filter((p) => p.present)

  const portraitInner = photo ? (
    <img
      data-testid="passport-card-profile-image"
      src={photo}
      alt={model.name ? `${model.name} — profile photo` : "Candidate profile photo"}
      width={portrait}
      height={portrait}
      style={{
        width: portrait,
        height: portrait,
        borderRadius: radius,
        objectFit: "cover",
        display: "block",
        border: `1px solid ${C.line}`,
      }}
    />
  ) : (
    <div
      data-testid="passport-card-avatar"
      style={{
        width: portrait,
        height: portrait,
        borderRadius: radius,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "linear-gradient(135deg,#6366f1,#4338ca)",
        color: "#fff",
        fontWeight: 700,
        fontSize: 32,
        letterSpacing: "0.02em",
        border: `1px solid ${C.indigoLine}`,
      }}
    >
      {initials}
    </div>
  )

  return (
    <div
      data-testid={`passport-card-${variant}`}
      style={{
        width: "100%",
        maxWidth: 480,
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderRadius: 20,
        padding: "20px 22px 22px",
        color: C.ink,
        background: C.paper,
        border: `1px solid ${C.line}`,
        boxShadow: "0 1px 2px rgba(10,14,26,0.04), 0 16px 40px -24px rgba(30,27,75,0.25)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Subtle brand accent — a quiet hairline, never a loud gradient. */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: "linear-gradient(90deg,#4f46e5 0%,#6366f1 55%,#10b981 100%)",
          opacity: 0.9,
        }}
      />

      {/* Top bar — brand + public status */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9.5, letterSpacing: "0.22em", color: C.indigo }}>
            VERIBRIDGE AI
          </span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, letterSpacing: "0.14em", color: C.ink, fontWeight: 600 }}>
            VERIFIED WORK PASSPORT
          </span>
        </div>
        <span
          data-testid="passport-card-status"
          style={{
            flexShrink: 0,
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: "3px 10px",
            borderRadius: 999,
            fontSize: 10.5,
            fontWeight: 600,
            whiteSpace: "nowrap",
            background: isLive ? C.emeraldSoft : C.wash,
            color: isLive ? C.emerald : C.muted,
            border: `1px solid ${isLive ? C.emeraldLine : C.line}`,
          }}
        >
          {isLive ? "✓ " : ""}
          {model.publicStatus}
        </span>
      </div>

      {/* Identity — professional portrait (photo/initials) + name / role / program.
          No QR or barcode on the card face. */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div data-testid="passport-card-portrait" style={{ position: "relative", flexShrink: 0, width: portrait, height: portrait }}>
          {portraitInner}
          {/* Subtle verified check badge once the passport is published. */}
          {isLive && (
            <span
              data-testid="passport-card-verified-badge"
              aria-label="Verified"
              title="Verified Work Passport"
              style={{
                position: "absolute",
                right: -6,
                bottom: -6,
                width: 26,
                height: 26,
                borderRadius: "50%",
                background: "#10b981",
                border: "2px solid #ffffff",
                boxShadow: "0 1px 3px rgba(10,14,26,0.18)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 13,
                color: "#fff",
                fontWeight: 700,
              }}
            >
              ✓
            </span>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
          <h2 data-testid="passport-card-name" style={{ fontSize: 20, color: C.ink, margin: 0, lineHeight: 1.2, fontWeight: 700, letterSpacing: "-0.01em" }}>
            {model.name || "Verified candidate profile"}
          </h2>
          <p data-testid="passport-card-headline" style={{ fontSize: 13, color: C.inkSoft, margin: 0, fontWeight: 500 }}>
            {model.headline}
          </p>
          {model.program && (
            <p data-testid="passport-card-program" style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              🎓 {model.program}
              {model.region ? ` · ${model.region}` : ""}
            </p>
          )}
        </div>
      </div>

      {/* Role / capability areas — only the selected areas, capped by the caller */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <span style={sectionLabel}>Role areas</span>
        {shownCapabilities.length === 0 ? (
          <p data-testid="passport-card-no-capabilities" style={{ fontSize: 12, color: C.muted, margin: 0 }}>
            Role areas appear once your skills have attached evidence.
          </p>
        ) : (
          <div data-testid="passport-card-capabilities" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {shownCapabilities.map((cap) => (
              <CapabilityChip
                key={cap.label}
                cap={cap}
                onClick={onCapabilityClick ? () => onCapabilityClick(cap) : undefined}
                href={capabilityHref ? capabilityHref(cap) : undefined}
              />
            ))}
          </div>
        )}
      </div>

      {/* Proof sources — quiet, neutral chips for the evidence types that actually
          back this passport (present sources only). Honest coverage language:
          "evidence available", never a score or a rank. */}
      {presentProof.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
          <span style={sectionLabel}>Proof sources</span>
          <div data-testid="passport-card-proof-sources" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {presentProof.map((p) => (
              <span
                key={p.label}
                data-testid="passport-card-proof-chip"
                data-label={p.label}
                title={`${p.label} evidence is available in the full Passport`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "4px 10px",
                  borderRadius: 999,
                  fontSize: 11.5,
                  fontWeight: 600,
                  background: C.wash,
                  color: C.inkSoft,
                  border: `1px solid ${C.lineSoft}`,
                }}
              >
                <span aria-hidden style={{ color: C.emerald, fontSize: 11, lineHeight: 1 }}>✓</span>
                {p.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Verification summary — a neutral recruiter-safe line, never a score. */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          flexWrap: "wrap",
          paddingTop: 14,
          borderTop: `1px solid ${C.lineSoft}`,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <p
            data-testid="passport-card-verification-summary"
            style={{ fontSize: 12.5, color: C.ink, margin: 0, fontWeight: 600 }}
          >
            Evidence-backed project profile
          </p>
          <p data-testid="passport-card-evidence-line" style={{ fontSize: 11.5, color: C.muted, margin: 0 }}>
            {model.evidence.projectCount} {model.evidence.projectCount === 1 ? "project" : "projects"} ·{" "}
            {model.evidence.proofTypeCount} proof {model.evidence.proofTypeCount === 1 ? "type" : "types"} · recruiter-safe
          </p>
        </div>
        <span
          data-testid="passport-card-trust-line"
          style={{ fontSize: 10.5, fontWeight: 600, color: C.faint, letterSpacing: "0.02em", whiteSpace: "nowrap" }}
        >
          {isLive ? "Verified report available" : "Recruiter-safe public view"}
        </span>
      </div>

      {footer}
    </div>
  )
}

const sectionLabel: CSSProperties = {
  fontSize: 9.5,
  color: "#9aa3b2",
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.14em",
}

/** A high-level role-area pill; deep-links to its strongest underlying skill. */
function CapabilityChip({
  cap,
  onClick,
  href,
}: {
  cap: PassportCardCapability
  onClick?: () => void
  href?: string
}) {
  const dot = STATUS_DOT[cap.status] ?? "#6366f1"
  const inner = (
    <>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, flexShrink: 0 }} />
      {cap.label}
    </>
  )
  const style: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "5px 11px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    background: C.indigoSoft,
    color: C.indigoDeep,
    border: `1px solid ${C.indigoLine}`,
    textDecoration: "none",
    cursor: onClick || href ? "pointer" : "default",
  }
  const title = `See the evidence behind ${cap.label} (${cap.skill})`

  if (onClick) {
    return (
      <button type="button" data-testid="passport-card-capability" data-label={cap.label} onClick={onClick} title={title} style={style}>
        {inner}
      </button>
    )
  }
  if (href) {
    return (
      <a data-testid="passport-card-capability" data-label={cap.label} href={href} title={title} style={style}>
        {inner}
      </a>
    )
  }
  return (
    <span data-testid="passport-card-capability" data-label={cap.label} style={style}>
      {inner}
    </span>
  )
}
