"use client"

import type { CSSProperties } from "react"

import type { BeamCardModel } from "@/lib/beam-card"

import { QrCode } from "./QrCode"

/**
 * The premium Beam Card face — a full-screen, boarding-pass-quality verified
 * credential built for the in-person handoff at `/beam`: identity + role areas +
 * top proof-backed skills + verified projects on the upper panel, then a
 * perforated divider into a clean, career-fair-scannable QR stub that opens the
 * live public Passport with no login.
 *
 * Purely presentational: it renders ONLY the already-safe {@link BeamCardModel}
 * (the same recruiter-safe fields the Passport Card and public Passport show) —
 * never raw evidence, private documents, internal ids, or numeric scores. One
 * trust mark only (the verified pill in the header); no fake certification, no
 * fake score, no wallet passes. The ONLY value the QR ever encodes is the
 * public Passport URL.
 */
export function BeamCard({ model }: { model: BeamCardModel }) {
  const photo = model.profileImageUrl
  const portrait = 64

  return (
    <div
      data-testid="beam-card"
      style={{
        width: "100%",
        maxWidth: 430,
        borderRadius: 26,
        background: C.paper,
        border: `1px solid ${C.line}`,
        boxShadow: "0 1px 2px rgba(10,14,26,0.05), 0 28px 64px -32px rgba(30,27,75,0.35)",
        overflow: "hidden",
        position: "relative",
        color: C.ink,
      }}
    >
      {/* Quiet brand hairline — the same accent the Passport Card carries. */}
      <div
        aria-hidden
        style={{
          height: 3,
          background: "linear-gradient(90deg,#4f46e5 0%,#6366f1 55%,#10b981 100%)",
          opacity: 0.9,
        }}
      />

      {/* ── Upper panel: identity + proof summary ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "18px 22px 20px" }}>
        {/* Brand row + the ONE trust mark. */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.22em", color: C.indigo }}>
              VERIBRIDGE AI
            </span>
            <span style={{ fontFamily: MONO, fontSize: 12, letterSpacing: "0.14em", fontWeight: 600, color: C.ink }}>
              VERIFIED WORK PASSPORT
            </span>
          </div>
          <span
            data-testid="beam-card-verified-pill"
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
              background: C.emeraldSoft,
              color: C.emerald,
              border: `1px solid ${C.emeraldLine}`,
            }}
          >
            ✓ Verified public Passport
          </span>
        </div>

        {/* Identity — portrait + name / headline / program. */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {photo ? (
            <img
              data-testid="beam-card-profile-image"
              src={photo}
              alt={model.name ? `${model.name} — profile photo` : "Candidate profile photo"}
              width={portrait}
              height={portrait}
              style={{
                width: portrait,
                height: portrait,
                borderRadius: 16,
                objectFit: "cover",
                display: "block",
                border: `1px solid ${C.line}`,
                flexShrink: 0,
              }}
            />
          ) : (
            <div
              data-testid="beam-card-avatar"
              style={{
                width: portrait,
                height: portrait,
                borderRadius: 16,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "linear-gradient(135deg,#6366f1,#4338ca)",
                color: "#fff",
                fontWeight: 700,
                fontSize: 24,
                letterSpacing: "0.02em",
                border: `1px solid ${C.indigoLine}`,
                flexShrink: 0,
              }}
            >
              {model.initials || "★"}
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 3, minWidth: 0 }}>
            <h2
              data-testid="beam-card-name"
              style={{ fontSize: 20, fontWeight: 700, margin: 0, lineHeight: 1.2, letterSpacing: "-0.01em", color: C.ink }}
            >
              {model.name || "Verified candidate profile"}
            </h2>
            <p data-testid="beam-card-headline" style={{ fontSize: 13, color: C.inkSoft, margin: 0, fontWeight: 500 }}>
              {model.headline}
            </p>
            {model.program && (
              <p data-testid="beam-card-program" style={{ fontSize: 12, color: C.muted, margin: 0 }}>
                🎓 {model.program}
                {model.region ? ` · ${model.region}` : ""}
              </p>
            )}
          </div>
        </div>

        {/* Role areas. */}
        {model.roleAreas.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={sectionLabel}>Role areas</span>
            <div data-testid="beam-card-role-areas" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {model.roleAreas.map((label) => (
                <span
                  key={label}
                  data-testid="beam-card-role-area"
                  data-label={label}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "4px 11px",
                    borderRadius: 999,
                    fontSize: 11.5,
                    fontWeight: 600,
                    background: C.indigoSoft,
                    color: C.indigoDeep,
                    border: `1px solid ${C.indigoLine}`,
                  }}
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Top proof-backed skills — qualitative labels only, never a score. */}
        {model.topSkills.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={sectionLabel}>Top proof-backed skills</span>
            <div data-testid="beam-card-skills" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {model.topSkills.map((s) => (
                <div
                  key={s.name}
                  data-testid="beam-card-skill"
                  data-label={s.name}
                  style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}
                >
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: C.inkSoft, minWidth: 0 }}>{s.name}</span>
                  <span style={{ fontSize: 10.5, fontWeight: 600, color: C.emerald, whiteSpace: "nowrap" }}>
                    {s.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Verified projects — published public reports only. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={sectionLabel}>Verified projects</span>
          {model.topProjects.length === 0 ? (
            <p data-testid="beam-card-projects-empty" style={{ fontSize: 12, color: C.muted, margin: 0 }}>
              Verified projects coming soon
            </p>
          ) : (
            <div data-testid="beam-card-projects" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {model.topProjects.map((p) => (
                <div
                  key={p.title}
                  data-testid="beam-card-project"
                  style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, fontWeight: 600, color: C.inkSoft }}
                >
                  <span aria-hidden style={{ color: C.emerald, fontSize: 11, lineHeight: 1 }}>✓</span>
                  {p.title}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Proof sources — present sources only, quiet neutral chips. */}
        {model.proofSources.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={sectionLabel}>Proof sources</span>
            <div data-testid="beam-card-proof-sources" style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {model.proofSources.map((label) => (
                <span
                  key={label}
                  data-testid="beam-card-proof-chip"
                  data-label={label}
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
                  {label}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Perforated divider — the boarding-pass tear line into the QR stub. ── */}
      <div aria-hidden style={{ position: "relative", height: 0, borderTop: `2px dashed ${C.line}` }}>
        <span style={{ ...notch, left: -12 }} />
        <span style={{ ...notch, right: -12 }} />
      </div>

      {/* ── QR stub — the scan target. ── */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 10,
          padding: "20px 22px 18px",
          background: C.wash,
        }}
      >
        <QrCode value={model.publicPassportUrl} size={224} data-testid="beam-card-qr" />
        <p
          data-testid="beam-card-qr-caption"
          style={{ fontSize: 13, fontWeight: 600, color: C.inkSoft, margin: 0, textAlign: "center" }}
        >
          Scan to open the live public Passport
        </p>
        {model.publicPassportUrl && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "center", width: "100%" }}>
            <div
              data-testid="beam-card-link"
              style={{
                fontFamily: MONO,
                fontSize: 11.5,
                color: C.ink,
                padding: "7px 11px",
                background: C.paper,
                border: `1px solid ${C.line}`,
                borderRadius: 9,
                wordBreak: "break-all",
                textAlign: "center",
                maxWidth: "100%",
              }}
            >
              {model.publicPassportUrl}
            </div>
            <span data-testid="beam-card-no-login" style={{ fontSize: 11, color: C.muted }}>
              No login required
            </span>
          </div>
        )}
        <p
          data-testid="beam-card-trust-line"
          style={{ fontSize: 10.5, fontWeight: 600, color: C.faint, margin: 0, textAlign: "center", letterSpacing: "0.02em" }}
        >
          Public-safe proof summary — private evidence protected
        </p>
      </div>
    </div>
  )
}

const MONO = "'JetBrains Mono', monospace"

/** Light-mode palette for the Beam Card face (matches the Passport Card). */
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

const sectionLabel: CSSProperties = {
  fontSize: 9.5,
  color: "#9aa3b2",
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.14em",
}

/** Boarding-pass notch — a page-background circle biting into the tear line. */
const notch: CSSProperties = {
  position: "absolute",
  top: -13,
  width: 24,
  height: 24,
  borderRadius: "50%",
  background: "#eef1f7",
  border: "1px solid #e6e8ef",
}
