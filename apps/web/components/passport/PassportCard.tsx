"use client"

import type { CSSProperties, ReactNode } from "react"

import type { PassportCardCapability, PassportCardModel } from "@/lib/passport-card"
import { QrCode } from "./QrCode"

/** Qualitative status → dot colour (never a numeric score). */
const STATUS_DOT: Record<string, string> = {
  Demonstrated: "#34d399",
  "Evidence observed": "#34d399",
  "Partially demonstrated": "#fbbf24",
  "Supporting evidence": "#60a5fa",
  "Needs review": "#fb7185",
  "Not assessed": "#94a3b8",
}

const PROOF_SHORT: Record<string, string> = {
  "GitHub Proof": "GitHub",
  "Document Proof": "Document",
  "Website Proof": "Website",
  "Project Defense": "Defense",
  "Video Evidence": "Video",
}

/**
 * The Verified Passport Card — a compact, premium digital-credential (ATM/ID-card
 * style) shared by the private preview and the public `/card/[slug]` route. It
 * answers a recruiter's five-second question — who is this, what role areas can
 * they apply for, what proof exists, how do I open the full Passport — WITHOUT
 * being a report: no featured-project list, no raw evidence, no scores.
 *
 * The profile area doubles as the scan target: when the passport is published a
 * QR encoding the public Work Passport URL sits behind the candidate's initials,
 * so scanning the profile opens the full verified Passport. Role chips deep-link
 * to real, evidence-backed skills (same-page for the private preview via
 * {@link onCapabilityClick}; cross-page for the public card via {@link capabilityHref}).
 */
export function PassportCard({
  model,
  variant,
  onCapabilityClick,
  capabilityHref,
  footer,
}: {
  model: PassportCardModel
  variant: "private" | "public"
  /** Same-page role-chip selection (private preview → filter the evidence map). */
  onCapabilityClick?: (cap: PassportCardCapability) => void
  /** Cross-page role-chip deep link (public card → full Passport skill evidence). */
  capabilityHref?: (cap: PassportCardCapability) => string
  /** CTAs / recruiter-safe note rendered below the card body. */
  footer?: ReactNode
}) {
  const isLive = model.isPublished
  // Scanning the profile opens the FULL public Work Passport (never a private route).
  const qrValue = model.publicPassportUrl
  const initials = model.initials || "★"
  const photo = model.profileImageUrl

  // The profile node is the scan target's centre: the candidate's photo when a
  // public-safe URL exists, else their initials. Rendered at two sizes — small as
  // the QR overlay (published), large as the standalone profile (private/unpublished).
  const profileNode = (size: number, fontSize: number) => {
    const radius = Math.round(size * 0.24)
    if (photo) {
      return (
        <img
          data-testid="passport-card-profile-image"
          src={photo}
          alt={model.name ? `${model.name} — profile photo` : "Candidate profile photo"}
          width={size}
          height={size}
          style={{
            width: size,
            height: size,
            borderRadius: radius,
            objectFit: "cover",
            display: "block",
            border: "1px solid rgba(255,255,255,0.16)",
          }}
        />
      )
    }
    return (
      <div
        data-testid="passport-card-avatar"
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg,#6366f1,#4338ca)",
          color: "#fff",
          fontWeight: 700,
          fontSize,
          letterSpacing: "0.02em",
        }}
      >
        {initials}
      </div>
    )
  }

  return (
    <div
      data-testid={`passport-card-${variant}`}
      style={{
        width: "100%",
        maxWidth: 480,
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderRadius: 18,
        padding: 20,
        color: "#fff",
        background: "linear-gradient(135deg,#0a0e1a 0%,#1e1b4b 52%,#312e81 100%)",
        border: "1px solid rgba(255,255,255,0.10)",
        boxShadow: "0 10px 30px -12px rgba(30,27,75,0.55)",
      }}
    >
      {/* Top bar — brand + public status */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9.5, letterSpacing: "0.22em", color: "#a5b4fc" }}>
            VERIBRIDGE AI
          </span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, letterSpacing: "0.16em", color: "#fff", fontWeight: 600 }}>
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
            padding: "3px 9px",
            borderRadius: 999,
            fontSize: 10.5,
            fontWeight: 600,
            whiteSpace: "nowrap",
            background: isLive ? "rgba(52,211,153,0.16)" : "rgba(255,255,255,0.10)",
            color: isLive ? "#6ee7b7" : "#cbd5e1",
            border: `1px solid ${isLive ? "rgba(52,211,153,0.4)" : "rgba(255,255,255,0.18)"}`,
          }}
        >
          {isLive ? "✓ " : ""}
          {model.publicStatus}
        </span>
      </div>

      {/* Identity + profile/QR scan area */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ flexShrink: 0 }}>
          {qrValue ? (
            <QrCode
              value={qrValue}
              size={104}
              overlay={profileNode(42, initials.length > 1 ? 15 : 18)}
              label="Scan profile → full Passport"
              data-testid="passport-card-qr"
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <div
                data-testid="passport-card-avatar-only"
                style={{
                  width: 104,
                  height: 104,
                  borderRadius: 14,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  overflow: "hidden",
                  background: photo ? "transparent" : "linear-gradient(135deg,#312e81,#4338ca)",
                  border: "1px solid rgba(255,255,255,0.14)",
                }}
              >
                {profileNode(102, 34)}
              </div>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.5)", textAlign: "center", maxWidth: 128 }}>
                Publish to add scan code
              </span>
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
          <h2 data-testid="passport-card-name" style={{ fontSize: 20, color: "#fff", margin: 0, lineHeight: 1.2, fontWeight: 700 }}>
            {model.name || "Verified candidate profile"}
          </h2>
          <p data-testid="passport-card-headline" style={{ fontSize: 13, color: "rgba(255,255,255,0.82)", margin: 0, fontWeight: 500 }}>
            {model.headline}
          </p>
          {model.program && (
            <p data-testid="passport-card-program" style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", margin: 0 }}>
              🎓 {model.program}
            </p>
          )}
        </div>
      </div>

      {/* Role / capability areas */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <span style={sectionLabel}>Role areas</span>
        {model.capabilities.length === 0 ? (
          <p data-testid="passport-card-no-capabilities" style={{ fontSize: 12, color: "rgba(255,255,255,0.55)", margin: 0 }}>
            Role areas appear once your skills have attached evidence.
          </p>
        ) : (
          <div data-testid="passport-card-capabilities" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {model.capabilities.map((cap) => (
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

      {/* Proof coverage + evidence line */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        <span style={sectionLabel}>Evidence</span>
        <div data-testid="passport-card-proof-coverage" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {model.proofCoverage.map((c) => (
            <span
              key={c.label}
              data-testid="passport-card-proof-item"
              data-source={c.label}
              data-present={c.present ? "true" : "false"}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "3px 8px",
                borderRadius: 999,
                fontSize: 10.5,
                fontWeight: 600,
                background: c.present ? "rgba(52,211,153,0.14)" : "rgba(255,255,255,0.05)",
                color: c.present ? "#6ee7b7" : "rgba(255,255,255,0.4)",
                border: `1px solid ${c.present ? "rgba(52,211,153,0.34)" : "rgba(255,255,255,0.10)"}`,
              }}
            >
              {c.present ? "✓" : "–"} {PROOF_SHORT[c.label] ?? c.label}
            </span>
          ))}
        </div>
        <p data-testid="passport-card-evidence-line" style={{ fontSize: 11.5, color: "rgba(255,255,255,0.7)", margin: 0 }}>
          {model.evidence.projectCount} {model.evidence.projectCount === 1 ? "project" : "projects"} ·{" "}
          {model.evidence.proofTypeCount} proof {model.evidence.proofTypeCount === 1 ? "type" : "types"} · recruiter-safe
        </p>
      </div>

      {footer}
    </div>
  )
}

const sectionLabel: CSSProperties = {
  fontSize: 9.5,
  color: "rgba(255,255,255,0.5)",
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
  const dot = STATUS_DOT[cap.status] ?? "#a5b4fc"
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
    background: "rgba(255,255,255,0.10)",
    color: "#fff",
    border: "1px solid rgba(255,255,255,0.16)",
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
