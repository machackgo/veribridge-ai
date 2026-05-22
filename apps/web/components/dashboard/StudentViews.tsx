"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useState } from "react";
import { DemoToast, useDemoToast } from "../ui/DemoToast";
import {
  applications,
  jobs,
  skillGaps,
  student,
  visaSignals,
} from "../../data/mock";
import { StudentProofSubmissionPanel } from "../skill-proof/student-proof-submission-panel";

/* ── Shared micro-components (minimal, not over-abstracted) ── */

function Mono({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <span style={{ fontFamily: "'JetBrains Mono', monospace", ...style }}>
      {children}
    </span>
  );
}

function PageHeader({ crumb, title, lede, compact }: { crumb: string; title: string; lede: ReactNode; compact?: boolean }) {
  return (
    <>
      <Mono style={{ fontSize: 11, letterSpacing: "0.16em", color: "var(--muted)", textTransform: "uppercase" }}>
        {crumb}
      </Mono>
      <h1 style={{ fontSize: compact ? 26 : 32, fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 4px", color: "var(--ink)" }}>
        {title}
      </h1>
      <p style={{ fontSize: 13, color: "var(--muted)", margin: compact ? "4px 0 10px" : "6px 0 24px", lineHeight: 1.5 }}>{lede}</p>
    </>
  );
}

function Card({ children, style, className }: { children: ReactNode; style?: React.CSSProperties; className?: string }) {
  return (
    <div
      className={`vb-card-hover ${className ?? ""}`}
      style={{
        background: "var(--paper)",
        border: "1px solid var(--line)",
        borderRadius: 14,
        padding: 20,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function CardHeader({ title, eyebrow }: { title: string; eyebrow?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
      <span style={{ fontWeight: 600, fontSize: 14, letterSpacing: "-0.01em" }}>{title}</span>
      {eyebrow && (
        <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase" }}>
          {eyebrow}
        </Mono>
      )}
    </div>
  );
}

function Stat({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <Mono
      style={{
        fontSize: 10,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        padding: "4px 8px",
        borderRadius: 999,
        fontWeight: 600,
        color,
        background: bg,
      }}
    >
      {label}
    </Mono>
  );
}

function Toggle({
  on = true,
  onToggle,
  label = "toggle",
}: {
  on?: boolean;
  onToggle?: () => void;
  label?: string;
}) {
  if (!onToggle) {
    // Static display mode (backward compat)
    return (
      <span
        style={{
          width: 38,
          height: 22,
          background: on ? "var(--emerald)" : "var(--line)",
          borderRadius: 99,
          position: "relative",
          display: "inline-block",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 2,
            left: on ? undefined : 2,
            right: on ? 2 : undefined,
            width: 18,
            height: 18,
            background: "#fff",
            borderRadius: "50%",
          }}
        />
      </span>
    );
  }
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onToggle}
      style={{
        width: 38,
        height: 22,
        borderRadius: 99,
        background: on ? "var(--emerald)" : "var(--line)",
        border: "none",
        cursor: "pointer",
        position: "relative",
        flexShrink: 0,
        transition: "background 0.15s",
        outline: "none",
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: on ? undefined : 2,
          right: on ? 2 : undefined,
          width: 18,
          height: 18,
          background: "#fff",
          borderRadius: "50%",
          boxShadow: "0 1px 3px rgba(0,0,0,.2)",
          transition: "all 0.15s",
          display: "block",
        }}
      />
    </button>
  );
}

function Btn({ children, style, ghost, onClick }: { children: ReactNode; style?: React.CSSProperties; ghost?: boolean; onClick?: () => void }) {
  return (
    <button
      type="button"
      className="vb-btn-lift"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "9px 14px",
        borderRadius: 9,
        fontSize: 13,
        fontWeight: 600,
        border: "1px solid transparent",
        cursor: "pointer",
        background: ghost ? "transparent" : "var(--ink)",
        color: ghost ? "var(--ink-2)" : "#fff",
        borderColor: ghost ? "var(--line-2)" : "transparent",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

function Bar({ pct, color = "linear-gradient(90deg,#f59e0b,#f43f5e)" }: { pct: number; color?: string }) {
  return (
    <div style={{ height: 5, borderRadius: 3, background: "var(--line)", overflow: "hidden", marginTop: 8 }}>
      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 3 }} />
    </div>
  );
}

/* ── Overview score ring ── */
function ScoreRing({ score }: { score: number }) {
  const r = 42;
  const circ = 2 * Math.PI * r; // 263.89
  const offset = circ * (1 - score / 100);
  return (
    <div style={{ width: 96, height: 96, position: "relative", flexShrink: 0 }}>
      <svg viewBox="0 0 100 100" style={{ width: "100%", height: "100%", transform: "rotate(-90deg)" }}>
        <circle cx="50" cy="50" r={r} fill="none" stroke="rgba(255,255,255,.15)" strokeWidth="7" />
        <circle
          cx="50" cy="50" r={r} fill="none"
          stroke="url(#scoreGrad)" strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
        />
        <defs>
          <linearGradient id="scoreGrad" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="#a5b4fc" />
            <stop offset="1" stopColor="#86efac" />
          </linearGradient>
        </defs>
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "grid",
          placeItems: "center",
          fontWeight: 600,
          fontSize: 30,
          letterSpacing: "-0.02em",
          color: "#fff",
        }}
      >
        {score}
      </div>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   STUDENT OVERVIEW  (direct port of prototype overview section)
   ──────────────────────────────────────────────────────────── */
export function StudentOverview() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Dashboard · Overview"
        title="Welcome back, Maya."
        lede={
          <>
            Your VeriBridge score is up{" "}
            <strong style={{ color: "var(--emerald)" }}>+14 in 30d</strong> — driven by 2 newly
            verified skills and a deployed Docker project. Two recruiters viewed your profile this week.
          </>
        }
      />

      {/* Row 1: 1.4fr 1fr 1fr */}
      <div className="vb-stagger" style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr", gap: 16 }}>
        {/* Score card hero */}
        <div
          style={{
            background: "linear-gradient(135deg,var(--ink),#1a2040 60%,#2a1a4a)",
            color: "#fff",
            position: "relative",
            overflow: "hidden",
            borderRadius: 14,
            padding: 20,
          }}
        >
          {/* Radial glow */}
          <div
            style={{
              position: "absolute",
              right: -60,
              top: -60,
              width: 240,
              height: 240,
              background: "radial-gradient(circle,rgba(139,92,246,.5),transparent 70%)",
              filter: "blur(20px)",
              pointerEvents: "none",
            }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18, position: "relative" }}>
            <span style={{ fontWeight: 600, fontSize: 14, color: "#fff" }}>VeriBridge Score</span>
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "rgba(255,255,255,.5)", textTransform: "uppercase" }}>Updated 2h ago</Mono>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 24, alignItems: "center", position: "relative" }}>
            <ScoreRing score={student.score} />
            <div>
              <Mono style={{ fontSize: 10, letterSpacing: "0.16em", color: "rgba(255,255,255,.5)", textTransform: "uppercase" }}>
                Career Readiness
              </Mono>
              <h2 style={{ margin: "6px 0 4px", fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" }}>
                Strong · Top 12% of CS &#39;26
              </h2>
              <div style={{ color: "#86efac", fontSize: 13, fontWeight: 500 }}>
                ↑ 14 in last 30 days
              </div>
            </div>
          </div>
          {/* Breakdown */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginTop: 18, position: "relative" }}>
            {[["Skills", 88], ["Proof", 79], ["Experience", 72], ["Polish", 86]].map(([l, v]) => (
              <div
                key={l}
                style={{
                  background: "rgba(255,255,255,.06)",
                  border: "1px solid rgba(255,255,255,.1)",
                  borderRadius: 9,
                  padding: "10px 12px",
                }}
              >
                <Mono style={{ fontSize: 9, letterSpacing: "0.14em", color: "rgba(255,255,255,.5)", textTransform: "uppercase" }}>{l}</Mono>
                <div style={{ fontSize: 16, fontWeight: 600, marginTop: 3 }}>{v}</div>
                <div style={{ height: 3, background: "rgba(255,255,255,.15)", borderRadius: 2, marginTop: 8, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${v}%`, background: "linear-gradient(90deg,#a5b4fc,#86efac)" }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Metric: Verified Skills (indigo) */}
        <div
          style={{
            background: "var(--indigo-soft)",
            border: "1px solid color-mix(in srgb,var(--indigo) 25%,transparent)",
            borderRadius: 14,
            padding: 20,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <span style={{ fontWeight: 600, fontSize: 14, color: "var(--indigo)" }}>Verified Skills</span>
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase" }}>Live</Mono>
          </div>
          <div style={{ fontSize: 34, fontWeight: 600, letterSpacing: "-0.025em", lineHeight: 1, color: "var(--indigo)" }}>
            {student.verifiedSkills}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
            {student.publicProof} with public proof · 6 pending
          </div>
        </div>

        {/* Metric: Top Match (emerald) */}
        <div
          style={{
            background: "var(--emerald-soft)",
            border: "1px solid color-mix(in srgb,var(--emerald) 25%,transparent)",
            borderRadius: 14,
            padding: 20,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <span style={{ fontWeight: 600, fontSize: 14, color: "var(--emerald)" }}>Top Match</span>
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase" }}>Today</Mono>
          </div>
          <div style={{ fontSize: 34, fontWeight: 600, letterSpacing: "-0.025em", lineHeight: 1, color: "var(--emerald)" }}>
            94%
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>Backend Engineer · NYC</div>
        </div>
      </div>

      {/* Row 2: 1fr 1fr */}
      <div className="vb-stagger" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        {/* Job matches */}
        <Card>
          <CardHeader title="Job matches" eyebrow="12 new this week" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { co: "St", bg: "var(--ink)", c: "#fff", role: "Backend Engineer, Intern", meta: "Stripe · NYC · F-1 OK", pct: 94, pctColor: "var(--emerald)", visaFit: 92, visaFitColor: "var(--emerald)" },
              { co: "Lr", bg: "#0d9488", c: "#fff", role: "Software Engineer Intern", meta: "Linear · Remote · F-1 OK", pct: 91, pctColor: "var(--emerald)", visaFit: 89, visaFitColor: "var(--emerald)" },
              { co: "Vc", bg: "#4f46e5", c: "#fff", role: "Full-stack Intern", meta: "Vercel · NYC · F-1 OK", pct: 88, pctColor: "var(--indigo)", visaFit: 85, visaFitColor: "var(--indigo)" },
              { co: "An", bg: "#f59e0b", c: "#fff", role: "SRE Intern", meta: "Anthropic · SF · sponsor required", pct: 83, pctColor: "var(--purple)", visaFit: 46, visaFitColor: "var(--amber)" },
            ].map((j) => (
              <div
                key={j.role}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto auto auto",
                  gap: 12,
                  alignItems: "center",
                  padding: 12,
                  border: "1px solid var(--line)",
                  borderRadius: 10,
                  background: "var(--bg-2)",
                  transition: "border-color 150ms ease, background 150ms ease",
                }}
              >
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    display: "grid",
                    placeItems: "center",
                    background: j.bg,
                    color: j.c,
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 12,
                    border: "1px solid var(--line)",
                    flexShrink: 0,
                  }}
                >
                  {j.co}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13, letterSpacing: "-0.005em" }}>{j.role}</div>
                  <Mono style={{ fontSize: 11, color: "var(--muted)", marginTop: 2, letterSpacing: "0.04em" }}>{j.meta}</Mono>
                </div>
                <div style={{ textAlign: "right" }}>
                  <Mono style={{ fontSize: 9, color: "var(--muted)", letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 500, display: "block" }}>Match</Mono>
                  <span style={{ fontWeight: 600, fontSize: 15, color: j.pctColor }}>{j.pct}%</span>
                </div>
                <div style={{ textAlign: "right", paddingLeft: 4, borderLeft: "1px solid var(--line)" }}>
                  <Mono style={{ fontSize: 9, color: "var(--muted)", letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 500, display: "block" }}>Visa</Mono>
                  <span style={{ fontWeight: 600, fontSize: 13, color: j.visaFitColor }}>{j.visaFit}%</span>
                </div>
                <span style={{ color: "var(--muted)" }}>→</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Skill gaps */}
        <Card>
          <CardHeader title="Skill gaps · ranked by impact" eyebrow="Updated daily" />
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {skillGaps.slice(0, 3).map((gap) => (
              <div
                key={gap.skill}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  gap: 6,
                  padding: "10px 12px",
                  border: "1px solid var(--line)",
                  borderRadius: 9,
                  background: "var(--bg-2)",
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 13 }}>{gap.skill}</div>
                <Mono style={{ fontSize: 11, color: "var(--muted)" }}>{gap.impact}% of saved jobs</Mono>
                <Mono style={{ gridColumn: "1/-1", fontSize: 11, color: "var(--muted)", letterSpacing: "0.04em" }}>
                  {gap.plan}
                </Mono>
                <Bar pct={gap.impact} />
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Row 3: 1.5fr 1fr */}
      <div className="vb-stagger" style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16, marginTop: 16 }}>
        {/* Application tracker */}
        <Card>
          <CardHeader title="Application tracker" eyebrow="7 active" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { co: "St", bg: "var(--ink)", c: "#fff", nm: "Stripe · Backend Eng. Intern", when: "Applied 4 days ago · CL tailored", status: "Interview", statusColor: "var(--purple)", statusBg: "var(--purple-soft)" },
              { co: "Lr", bg: "#0d9488", c: "#fff", nm: "Linear · SWE Intern", when: "Applied 8 days ago", status: "Applied", statusColor: "var(--indigo)", statusBg: "var(--indigo-soft)" },
              { co: "Vc", bg: "#4f46e5", c: "#fff", nm: "Vercel · Full-stack Intern", when: "Awaiting your edits", status: "Draft", statusColor: "var(--amber)", statusBg: "var(--amber-soft)" },
              { co: "Fg", bg: "#000", c: "#fff", nm: "Figma · Platform Intern", when: "Phone screen scheduled · Tue", status: "Interview", statusColor: "var(--purple)", statusBg: "var(--purple-soft)" },
              { co: "Ne", bg: "#1f2a44", c: "#fff", nm: "Netflix · Tools Intern", when: "Final round · offer pending", status: "Offer", statusColor: "var(--emerald)", statusBg: "var(--emerald-soft)" },
            ].map((t) => (
              <div
                key={t.nm}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto",
                  gap: 12,
                  alignItems: "center",
                  padding: "11px 12px",
                  border: "1px solid var(--line)",
                  borderRadius: 9,
                  background: "var(--bg-2)",
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 7,
                    display: "grid",
                    placeItems: "center",
                    background: t.bg,
                    color: t.c,
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 11,
                    border: "1px solid var(--line)",
                    flexShrink: 0,
                  }}
                >
                  {t.co}
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{t.nm}</div>
                  <Mono style={{ fontSize: 11, color: "var(--muted)", letterSpacing: "0.04em" }}>{t.when}</Mono>
                </div>
                <Mono
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    padding: "4px 8px",
                    borderRadius: 999,
                    fontWeight: 600,
                    color: t.statusColor,
                    background: t.statusBg,
                    whiteSpace: "nowrap",
                  }}
                >
                  {t.status}
                </Mono>
              </div>
            ))}
          </div>
        </Card>

        {/* Right column: NBA + activity + upload */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* NBA */}
          <div
            style={{
              background: "linear-gradient(135deg,var(--indigo-soft),var(--purple-soft))",
              border: "1px solid color-mix(in srgb,var(--indigo) 18%,transparent)",
              borderRadius: 14,
              padding: 20,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <span style={{ fontWeight: 600, fontSize: 14, color: "var(--indigo)" }}>Next Best Action</span>
              <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase" }}>AI · Today</Mono>
            </div>
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase", marginBottom: 6 }}>
              Why this matters
            </Mono>
            <h3 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--ink)" }}>
              Ship a small Kubernetes project this week.
            </h3>
            <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--ink-2)", lineHeight: 1.5 }}>
              It closes the highest-impact gap in your saved-job list — present in 68% of roles you&#39;re targeting — and we&#39;ll auto-link the deployed app as proof.
            </p>
            <Btn onClick={() => show("Project brief — AI-generated plan coming soon.")}>Open project brief →</Btn>
          </div>

          {/* Recent activity */}
          <Card>
            <CardHeader title="Recent activity" eyebrow="7d" />
            <div style={{ display: "flex", flexDirection: "column" }}>
              {[
                { ico: "●", t: "Docker skill verified — 3 evidence sources", d: "github · live deploy · CS 4515 transcript", when: "2h" },
                { ico: "↗", t: "Stripe recruiter viewed your profile", d: "Saw Docker, Distributed Systems, React proofs", when: "1d" },
                { ico: "⚐", t: "Cover letter draft — Vercel", d: "Awaiting your approval in queue", when: "2d" },
                { ico: "+", t: "Score increased: 68 → 82", d: "Driven by proof verification & new project", when: "5d" },
              ].map((a, i) => (
                <div
                  key={i}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr auto",
                    gap: 12,
                    alignItems: "flex-start",
                    padding: "12px 0",
                    borderBottom: i < 3 ? "1px solid var(--line)" : "none",
                  }}
                >
                  <div
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: 7,
                      background: "var(--bg-2)",
                      display: "grid",
                      placeItems: "center",
                      color: "var(--ink-2)",
                      flexShrink: 0,
                      border: "1px solid var(--line)",
                      fontSize: 12,
                    }}
                  >
                    {a.ico}
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, lineHeight: 1.4 }}>{a.t}</div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{a.d}</div>
                  </div>
                  <Mono style={{ fontSize: 10, color: "var(--muted)", letterSpacing: "0.06em", whiteSpace: "nowrap" }}>{a.when}</Mono>
                </div>
              ))}
            </div>
          </Card>

          {/* Upload evidence */}
          <div
            style={{
              border: "1px dashed var(--line-2)",
              borderRadius: 11,
              padding: 18,
              background: "var(--bg-2)",
              textAlign: "center",
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 9,
                background: "var(--paper)",
                border: "1px solid var(--line)",
                display: "grid",
                placeItems: "center",
                margin: "0 auto 10px",
                color: "var(--ink-2)",
                fontSize: 18,
              }}
            >
              ↑
            </div>
            <b style={{ display: "block", fontSize: 13, color: "var(--ink)", fontWeight: 600, marginBottom: 3 }}>
              Upload new evidence
            </b>
            <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
              Resume · transcript · project file · GitHub URL
            </p>
          </div>
        </div>
      </div>

      {/* ── Visa Fit Summary Strip ── */}
      <div style={{ marginTop: 16 }}>
        <div
          style={{
            background: "linear-gradient(135deg,var(--indigo-soft) 0%,var(--purple-soft) 100%)",
            border: "1px solid color-mix(in srgb,var(--indigo) 22%,transparent)",
            borderRadius: 14,
            padding: "18px 20px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: "var(--indigo)" }}>◎ Visa Fit · International Status</span>
              <Mono
                style={{
                  fontSize: 10,
                  color: "var(--indigo)",
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  background: "rgba(79,70,229,.12)",
                  padding: "2px 8px",
                  borderRadius: 999,
                  fontWeight: 700,
                }}
              >
                F-1 Active
              </Mono>
            </div>
            <Link
              href="/dashboard/visa-fit"
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: "var(--indigo)",
                textDecoration: "none",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              Full details →
            </Link>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 12 }}>
            {[
              { label: "Status", value: "F-1 Active", sub: "WPI · .edu verified", color: "var(--indigo)" },
              { label: "CPT Eligible", value: "Spring 2026", sub: "Upcoming window", color: "var(--indigo)" },
              { label: "OPT Planned", value: "June 2026", sub: "Post-completion", color: "var(--purple)" },
              { label: "STEM OPT", value: "Eligible", sub: "24-mo extension", color: "var(--emerald)" },
              { label: "Top Visa Match", value: "92%", sub: "Stripe Backend Intern", color: "var(--emerald)" },
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  background: "rgba(255,255,255,.65)",
                  borderRadius: 10,
                  padding: "12px 14px",
                  backdropFilter: "blur(8px)",
                  border: "1px solid rgba(255,255,255,.8)",
                }}
              >
                <Mono style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase" }}>
                  {item.label}
                </Mono>
                <div style={{ fontSize: 16, fontWeight: 700, color: item.color, marginTop: 4, letterSpacing: "-0.01em" }}>
                  {item.value}
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{item.sub}</div>
              </div>
            ))}
          </div>
          <p
            style={{
              margin: "14px 0 0",
              fontSize: 11,
              color: "var(--muted)",
              fontStyle: "italic",
            }}
          >
            VeriBridge AI provides career-readiness and job compatibility insights, not legal or immigration advice.
          </p>
        </div>
      </div>
    </div>
  );
}

/* ── PROFILE & PROOF ── */
export function StudentProfileProof() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        compact
        crumb="Dashboard · Profile & Proof"
        title="Your verified profile."
        lede="Every skill is anchored to evidence — GitHub commits, deployed apps, transcripts, and certifications."
      />

      {/* Profile card */}
      <Card style={{ marginBottom: 10, padding: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 16, alignItems: "center" }}>
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 14,
              background: "linear-gradient(135deg,#4f46e5,#8b5cf6)",
              color: "#fff",
              display: "grid",
              placeItems: "center",
              fontSize: 20,
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            MR
          </div>
          <div>
            <h2 style={{ margin: "0 0 2px", fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em" }}>Maya Reyes</h2>
            <Mono style={{ fontSize: 11, color: "var(--muted)", letterSpacing: "0.04em" }}>
              WPI · CS &#39;26 · GPA 3.84 · Worcester, MA
            </Mono>
            <div style={{ display: "flex", gap: 5, marginTop: 6, flexWrap: "wrap" }}>
              <Stat label="✓ .edu Verified" color="var(--emerald)" bg="var(--emerald-soft)" />
              <Stat label="F-1 · Visa OK" color="var(--indigo)" bg="var(--indigo-soft)" />
              <Stat label="Score 82 · Top 12%" color="var(--purple)" bg="var(--purple-soft)" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <Btn ghost onClick={() => show("Preview mode — recruiter view coming soon.")}>Preview as recruiter</Btn>
            <Btn onClick={() => show("Edit profile — coming soon.")}>Edit profile</Btn>
          </div>
        </div>
      </Card>

      {/* Evidence cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <StudentProofSubmissionPanel notify={show} />
        <Card>
          <CardHeader title="Suggested proof types" eyebrow="Not selected" />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {["GitHub repo", "LinkedIn post", "Certificate", "Report", "Demo link", "Dashboard"].map((item, index) => (
              <span
                key={`${item}-${index}`}
                style={{
                  fontSize: 12,
                  padding: "7px 11px",
                  background: "var(--bg-2)",
                  border: "1px dashed var(--line-2)",
                  color: "var(--muted)",
                  borderRadius: 999,
                  fontWeight: 600,
                }}
              >
                {item}
              </span>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ── JOB MATCHES ── */
export function StudentJobs() {
  const { show, msg } = useDemoToast();

  const filters = ["All roles · 240", "F-1 OK · 184", "Match ≥ 85 · 22", "Internship · 96", "New this week · 12"];
  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Dashboard · Job Matches"
        title="Roles ranked for you."
        lede="Match scores combine skill overlap, evidence relevance, visa compatibility, and historical placement signal — not just keywords."
      />
      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {filters.map((f, i) => (
          <span
            key={f}
            style={{
              fontSize: 12,
              padding: "7px 11px",
              borderRadius: 8,
              background: i === 0 ? "var(--ink)" : "var(--paper)",
              border: i === 0 ? "1px solid transparent" : "1px solid var(--line)",
              color: i === 0 ? "#fff" : "var(--ink-2)",
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            {f}
          </span>
        ))}
      </div>
      <Card>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {[
            { co: "St", bg: "var(--ink)", c: "#fff", role: "Backend Engineer, Intern · Stripe", meta: "NYC · F-1 OK · $48/hr · Summer 2026", matching: ["Docker", "TypeScript", "PostgreSQL"], missing: ["Kubernetes missing"], pct: 94, pctColor: "var(--emerald)" },
            { co: "Lr", bg: "#0d9488", c: "#fff", role: "Software Engineer Intern · Linear", meta: "Remote · F-1 OK · $52/hr · Summer 2026", matching: ["React", "TypeScript"], missing: ["GraphQL missing"], pct: 91, pctColor: "var(--emerald)" },
            { co: "Vc", bg: "#4f46e5", c: "#fff", role: "Full-stack Intern · Vercel", meta: "NYC · F-1 OK · $50/hr · Summer 2026", matching: ["React", "Node.js"], missing: ["Edge runtime missing"], pct: 88, pctColor: "var(--indigo)" },
            { co: "An", bg: "#f59e0b", c: "#fff", role: "SRE Intern · Anthropic", meta: "SF · Sponsorship required · Summer 2026", matching: ["Docker"], missing: ["Kubernetes missing", "Terraform missing"], pct: 83, pctColor: "var(--purple)" },
          ].map((j) => (
            <div
              key={j.role}
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr auto auto",
                gap: 14,
                alignItems: "center",
                padding: 14,
                border: "1px solid var(--line)",
                borderRadius: 11,
              }}
            >
              <div
                style={{
                  width: 42,
                  height: 42,
                  borderRadius: 10,
                  background: j.bg,
                  color: j.c,
                  display: "grid",
                  placeItems: "center",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  fontSize: 13,
                }}
              >
                {j.co}
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{j.role}</div>
                <Mono style={{ fontSize: 11, color: "var(--muted)", marginTop: 3, letterSpacing: "0.04em" }}>{j.meta}</Mono>
                <div style={{ display: "flex", gap: 5, marginTop: 8, flexWrap: "wrap" }}>
                  {j.matching.map((m) => (
                    <span key={m} style={{ fontSize: 10, padding: "3px 7px", background: "var(--emerald-soft)", color: "var(--emerald)", borderRadius: 4, fontWeight: 600 }}>✓ {m}</span>
                  ))}
                  {j.missing.map((m) => (
                    <span key={m} style={{ fontSize: 10, padding: "3px 7px", background: "var(--rose-soft)", color: "var(--rose)", borderRadius: 4, fontWeight: 600 }}>⚠ {m}</span>
                  ))}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <Mono style={{ fontSize: 24, fontWeight: 700, color: j.pctColor }}>{j.pct}%</Mono>
                <Mono style={{ fontSize: 9, color: "var(--muted)", letterSpacing: "0.14em", textTransform: "uppercase", fontWeight: 600, display: "block" }}>Match</Mono>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <Btn ghost style={{ fontSize: 11, padding: "6px 10px" }} onClick={() => show("Job saved to your list (demo).")}>Save</Btn>
                <Btn style={{ fontSize: 11, padding: "6px 10px" }} onClick={() => show("Preparing tailored application — backend coming soon.")}>Prepare app →</Btn>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── APPLICATIONS ── */
export function StudentApplications() {
  const cols = [
    { label: "Saved", count: 3, color: undefined as string | undefined, countBg: "var(--bg-2)", countColor: "var(--ink)", items: [{ nm: "Anthropic · SRE", when: "Saved 2d ago" }, { nm: "Plaid · Backend", when: "Saved 5d ago" }, { nm: "Notion · Platform", when: "Saved 1w ago" }] },
    { label: "Prepared", count: 2, color: undefined, countBg: "var(--bg-2)", countColor: "var(--ink)", items: [{ nm: "Vercel · Full-stack", when: "Resume v3 · CL drafted" }, { nm: "GitHub · DevTools", when: "Resume v3 · CL approved" }] },
    { label: "Applied", count: 4, color: "var(--indigo)", countBg: "var(--indigo-soft)", countColor: "var(--indigo)", items: [{ nm: "Linear · SWE", when: "Applied 8d · Resume v3" }, { nm: "Datadog · Backend", when: "Applied 6d · Resume v2" }, { nm: "Cloudflare · Platform", when: "Applied 3d · Resume v3" }, { nm: "Ramp · SWE", when: "Applied 1d · Resume v3" }] },
    { label: "Interview", count: 3, color: "var(--purple)", countBg: "var(--purple-soft)", countColor: "var(--purple)", items: [{ nm: "Stripe · Backend", when: "Round 2 · Tue 3pm" }, { nm: "Figma · Platform", when: "Phone screen · Wed" }, { nm: "Retool · Frontend", when: "Take-home submitted" }] },
    { label: "Offer", count: 1, color: "var(--emerald)", countBg: "var(--emerald-soft)", countColor: "var(--emerald)", items: [{ nm: "Netflix · Tools", when: "$ Decision by Fri", special: true }] },
    { label: "Rejected", count: 1, color: "var(--rose)", countBg: "var(--bg-2)", countColor: "var(--ink)", items: [{ nm: "Airbnb · SWE", when: "Final round · feedback saved" }] },
  ];
  return (
    <div>
      <PageHeader
        crumb="Dashboard · Applications"
        title="Application tracker."
        lede="14 applications across 6 stages. Resume + cover letter versions are tracked per company so you can A/B what's converting."
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 10, marginTop: 8 }}>
        {cols.map((col) => (
          <div key={col.label} style={{ background: "var(--paper)", border: "1px solid var(--line)", borderRadius: 11, padding: 14, minHeight: 380 }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: col.color || "var(--muted)", marginBottom: 10, display: "flex", justifyContent: "space-between", fontWeight: 600 }}>
              <span>{col.label}</span>
              <span style={{ background: col.countBg, padding: "1px 6px", borderRadius: 4, color: col.countColor }}>{col.count}</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {col.items.map((item: { nm: string; when: string; special?: boolean }) => (
                <div
                  key={item.nm}
                  style={{
                    background: item.special ? "var(--emerald-soft)" : "var(--bg-2)",
                    border: item.special ? "1px solid color-mix(in srgb,var(--emerald) 25%,transparent)" : "1px solid var(--line)",
                    borderRadius: 8,
                    padding: 10,
                    opacity: col.label === "Rejected" ? 0.7 : 1,
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600 }}>{item.nm}</div>
                  <Mono style={{ fontSize: 10, color: item.special ? "var(--emerald)" : "var(--muted)", marginTop: 3, fontWeight: item.special ? 600 : 400 }}>{item.when}</Mono>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── SKILL GAPS ── */
export function StudentSkillGaps() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Dashboard · Skill Gaps"
        title="Close the gaps that matter."
        lede="Ranked by how often the missing skill appears in your saved-job set. Each gap pairs with a learning plan and a project that becomes provable evidence."
      />
      <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 16 }}>
        <Card>
          <CardHeader title="Missing skills · ranked by impact" eyebrow="Updated daily" />
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {skillGaps.map((gap, i) => {
              const impact = i === 0 ? { label: "HIGH IMPACT", color: "var(--rose)", bg: "var(--rose-soft)" } : { label: "MED IMPACT", color: "var(--amber)", bg: "var(--amber-soft)" };
              return (
                <div key={gap.skill} style={{ padding: 14, border: "1px solid var(--line)", borderRadius: 10, background: "var(--bg-2)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{gap.skill}</div>
                      <Mono style={{ fontSize: 11, color: "var(--muted)", marginTop: 3, letterSpacing: "0.04em" }}>
                        In {gap.impact}% of saved jobs · {gap.plan}
                      </Mono>
                    </div>
                    <Mono
                      style={{
                        fontSize: 11,
                        padding: "4px 9px",
                        borderRadius: 5,
                        background: impact.bg,
                        color: impact.color,
                        fontWeight: 700,
                        letterSpacing: "0.1em",
                      }}
                    >
                      {impact.label}
                    </Mono>
                  </div>
                  <Bar pct={gap.readiness} />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--muted)", fontFamily: "'JetBrains Mono', monospace", marginTop: 5 }}>
                    <span>Your readiness · {gap.readiness}%</span>
                    <span>Target · 75%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* NBA */}
          <div
            style={{
              background: "linear-gradient(135deg,var(--indigo-soft),var(--purple-soft))",
              border: "1px solid color-mix(in srgb,var(--indigo) 18%,transparent)",
              borderRadius: 14,
              padding: 20,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <span style={{ fontWeight: 600, fontSize: 14, color: "var(--indigo)" }}>Recommended project</span>
              <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase" }}>AI</Mono>
            </div>
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--muted)", textTransform: "uppercase", marginBottom: 6 }}>
              Closes 1 high + 1 med-impact gap
            </Mono>
            <h3 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--ink)" }}>
              Deploy a multi-tier app on minikube
            </h3>
            <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--ink-2)", lineHeight: 1.5 }}>
              Container a simple React + Postgres app, deploy to local Kubernetes with Helm, expose via ingress. We&#39;ll auto-link the GitHub repo + screenshots as proof.
            </p>
            <Btn onClick={() => show("Project brief — AI-generated plan coming soon.")}>Open project brief →</Btn>
          </div>
          {/* Learning plan */}
          <Card>
            <CardHeader title="Learning plan · 6 weeks" eyebrow="Curated" />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[
                { week: "W1-2", title: "Kubernetes Up & Running", sub: "CKAD prep · ~12 hrs" },
                { week: "W3-4", title: "Build minikube project", sub: "Deployed proof artifact · ~16 hrs" },
                { week: "W5", title: "System Design drills", sub: "Mock interview pack · 5 sessions" },
                { week: "W6", title: "Re-score & verify", sub: "Expected lift: +6 to score" },
              ].map((w) => (
                <div
                  key={w.week}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "auto 1fr auto",
                    gap: 10,
                    padding: 10,
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                    background: "var(--bg-2)",
                    alignItems: "center",
                  }}
                >
                  <Mono style={{ fontSize: 11, fontWeight: 700, color: "var(--indigo)", width: 30 }}>{w.week}</Mono>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{w.title}</div>
                    <Mono style={{ fontSize: 10, color: "var(--muted)" }}>{w.sub}</Mono>
                  </div>
                  <span style={{ fontSize: 10, color: "var(--muted)" }}>→</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

/* ── VISA FIT ── */
export function StudentVisaFit() {
  const { show, msg } = useDemoToast();
  const [visaToggles, setVisaToggles] = useState([true, true, false]);

  const toggleVisa = (i: number) => {
    setVisaToggles(prev => {
      const next = [...prev];
      next[i] = !next[i];
      show("Visa setting updated locally.");
      return next;
    });
  };

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Dashboard · Visa Fit"
        title="Visa intelligence."
        lede="Career-readiness and job compatibility insights. Not legal advice."
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 16 }}>
        {visaSignals.map(([label, value], index) => (
          <div
            key={`${label}-${index}`}
            style={{
              background: "var(--indigo-soft)",
              border: "1px solid color-mix(in srgb,var(--indigo) 25%,transparent)",
              borderRadius: 14,
              padding: 20,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)", marginBottom: 8 }}>{label}</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--indigo)", lineHeight: 1.4 }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {jobs.map((job, index) => (
          <Card key={job.company}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{job.company} · {job.role}</div>
              <Mono
                style={{
                  fontSize: 11,
                  padding: "4px 8px",
                  borderRadius: 5,
                  background: job.visaFit < 50 ? "var(--amber-soft)" : "var(--emerald-soft)",
                  color: job.visaFit < 50 ? "var(--amber)" : "var(--emerald)",
                  fontWeight: 600,
                }}
              >
                {job.visaFit}% visa fit
              </Mono>
            </div>
            <Bar pct={job.visaFit} color={job.visaFit < 50 ? "linear-gradient(90deg,var(--amber),var(--rose))" : "linear-gradient(90deg,#4f46e5,#10b981)"} />
            {job.warning && (
              <p style={{ marginTop: 10, fontSize: 12, color: "var(--amber)", lineHeight: 1.5 }}>{job.warning}</p>
            )}
            <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>Show visa details to employer</span>
              <Toggle
                on={visaToggles[index % visaToggles.length]}
                onToggle={() => toggleVisa(index % visaToggles.length)}
                label={`Visa visibility for ${job.company}`}
              />
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ── MOCK INTERVIEW ── */
export function StudentMockInterview() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Dashboard · Mock Interview"
        title="Practice with the AI interviewer."
        lede="Realistic role-specific sessions. Technical, behavioral, and system-design — scored against rubrics used by top tech recruiters."
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 16 }}>
        {/* Score card */}
        <div
          style={{
            background: "linear-gradient(135deg,var(--ink),#1a2040 60%,#2a1a4a)",
            color: "#fff",
            borderRadius: 14,
            padding: 20,
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              right: -60,
              top: -60,
              width: 240,
              height: 240,
              background: "radial-gradient(circle,rgba(139,92,246,.5),transparent 70%)",
              filter: "blur(20px)",
              pointerEvents: "none",
            }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18, position: "relative" }}>
            <span style={{ fontWeight: 600, fontSize: 14, color: "#fff" }}>Interview readiness</span>
            <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: "rgba(255,255,255,.5)", textTransform: "uppercase" }}>Last session 4d</Mono>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 24, alignItems: "center", position: "relative" }}>
            <ScoreRing score={64} />
            <div>
              <Mono style={{ fontSize: 10, letterSpacing: "0.16em", color: "rgba(255,255,255,.5)", textTransform: "uppercase" }}>Readiness</Mono>
              <h2 style={{ margin: "6px 0 4px", fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" }}>Solid · keep practicing</h2>
              <div style={{ color: "#86efac", fontSize: 13, fontWeight: 500 }}>↑ 9 in last 14 days</div>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginTop: 18, position: "relative" }}>
            {[["Technical", 72], ["System", 48], ["Behavioral", 78], ["Comms", 68]].map(([l, v]) => (
              <div key={l} style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.1)", borderRadius: 9, padding: "10px 12px" }}>
                <Mono style={{ fontSize: 9, letterSpacing: "0.14em", color: "rgba(255,255,255,.5)", textTransform: "uppercase" }}>{l}</Mono>
                <div style={{ fontSize: 16, fontWeight: 600, marginTop: 3 }}>{v}</div>
                <div style={{ height: 3, background: "rgba(255,255,255,.15)", borderRadius: 2, marginTop: 8, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${v}%`, background: "linear-gradient(90deg,#a5b4fc,#86efac)" }} />
                </div>
              </div>
            ))}
          </div>
        </div>
        {/* Role selection */}
        <Card>
          <CardHeader title="Choose a role" eyebrow="Tailored to your saved jobs" />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 14 }}>
            {[
              { label: "Backend Engineer Intern", sub: "Stripe-style", selected: false },
              { label: "Full-stack Intern", sub: "Vercel · Linear style", selected: false },
              { label: "SRE / Platform", sub: "Anthropic · Cloudflare", selected: false },
              { label: "ML / Data", sub: "Anthropic · OpenAI style", selected: false },
            ].map((r) => (
              <div
                key={r.label}
                style={{
                  padding: 14,
                  border: r.selected ? "2px solid var(--indigo)" : "1px solid var(--line)",
                  borderRadius: 10,
                  background: r.selected ? "var(--indigo-soft)" : "var(--bg-2)",
                  cursor: "pointer",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600 }}>{r.label}</div>
                <Mono style={{ fontSize: 11, color: r.selected ? "var(--indigo)" : "var(--muted)", marginTop: 3, letterSpacing: "0.04em" }}>{r.sub}</Mono>
              </div>
            ))}
          </div>
          <Btn
            style={{ width: "100%", justifyContent: "center", padding: 12 }}
            onClick={() => show("Mock interview session starting... This is a demo — AI interviewer coming soon.")}
          >
            ▶ Start mock interview · ~45 min
          </Btn>
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        <Card>
          <CardHeader title="Sample technical questions" eyebrow="Backend Eng." />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { q: "Rate-limit a public API", sub: "System design · 30 min" },
              { q: "Implement an LRU cache", sub: "Coding · 25 min · Python" },
              { q: "Postgres index strategy for a 100M-row table", sub: "Architecture · 20 min" },
              { q: "Debug a flaky distributed test", sub: "Practical · 25 min" },
            ].map((q) => (
              <div key={q.q} style={{ padding: 11, border: "1px solid var(--line)", borderRadius: 8, background: "var(--bg-2)" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{q.q}</div>
                <Mono style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>{q.sub}</Mono>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Sample behavioral questions" eyebrow="Universal" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { q: "Walk me through a project you shipped.", sub: "STAR · 5 min" },
              { q: "A time you disagreed with a teammate.", sub: "Conflict · 4 min" },
              { q: "Hardest bug you've debugged.", sub: "Technical narrative · 5 min" },
              { q: "Why this company?", sub: "Motivation · 2 min" },
            ].map((q) => (
              <div key={q.q} style={{ padding: 11, border: "1px solid var(--line)", borderRadius: 8, background: "var(--bg-2)" }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{q.q}</div>
                <Mono style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>{q.sub}</Mono>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ── SETTINGS ── */
export function StudentSettings() {
  const { show, msg } = useDemoToast();

  const [notifications, setNotifications] = useState([
    { label: "New high-match jobs", sub: "Email · 1× daily digest", on: true },
    { label: "Recruiter views your profile", sub: "Email · real-time", on: true },
    { label: "Application status updates", sub: "Email + push", on: true },
    { label: "Weekly progress report", sub: "Email · Monday 8am", on: false },
  ]);

  const toggleNotif = (i: number) => {
    setNotifications(prev => {
      const next = [...prev];
      next[i] = { ...next[i], on: !next[i].on };
      show(`${next[i].label}: ${next[i].on ? "enabled" : "disabled"}`);
      return next;
    });
  };

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Account · Settings"
        title="Settings."
        lede="Profile, target roles, notifications, and account controls."
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Profile */}
        <Card>
          <CardHeader title="Profile" />
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {[
              { label: "Name", value: "Maya Reyes", disabled: false },
              { label: ".edu email · verified", value: "maya.reyes@wpi.edu", disabled: true },
              { label: "Major · grad year", value: "", disabled: false },
              { label: "Location preference", value: "", disabled: false },
            ].map((f) => (
              <label key={f.label} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <Mono style={{ fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--muted)", fontWeight: 600 }}>{f.label}</Mono>
                <input
                  defaultValue={f.value}
                  disabled={f.disabled}
                  placeholder={f.label === "Major · grad year" ? "Add your major in onboarding" : f.label === "Location preference" ? "Add location preferences in onboarding" : undefined}
                  style={{
                    fontFamily: "inherit",
                    padding: "9px 12px",
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                    background: "var(--bg-2)",
                    color: f.disabled ? "var(--muted)" : "var(--ink)",
                    fontSize: 14,
                  }}
                />
              </label>
            ))}
          </div>
        </Card>
        {/* Target roles */}
        <Card>
          <CardHeader title="Target roles" eyebrow="Drives matching" />
          <div style={{ display: "grid", gap: 12 }}>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
              No target roles selected yet. Add the roles you want to apply for.
            </p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {["Suggested: Backend Engineer", "Suggested: Full-stack Engineer", "Suggested: SRE / Platform"].map((r) => (
                <span
                  key={r}
                  style={{
                    fontSize: 12,
                    padding: "6px 11px",
                    background: "var(--bg-2)",
                    border: "1px dashed var(--line-2)",
                    color: "var(--muted)",
                    borderRadius: 999,
                    fontWeight: 600,
                  }}
                >
                  {r}
                </span>
              ))}
            </div>
          </div>
          <div style={{ marginTop: 14, borderTop: "1px solid var(--line)", paddingTop: 14 }}>
            <CardHeader title="Compensation floor" />
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
              No salary preference set yet. Add compensation targets when you are ready.
            </p>
          </div>
        </Card>
        {/* Notifications */}
        <Card>
          <CardHeader title="Notification preferences" />
          <div style={{ display: "flex", flexDirection: "column" }}>
            {notifications.map((n, i) => (
              <label key={n.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 0", borderBottom: i < notifications.length - 1 ? "1px solid var(--line)" : "none", cursor: "pointer" }}>
                <span>
                  <b style={{ fontSize: 13 }}>{n.label}</b>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{n.sub}</div>
                </span>
                <Toggle on={n.on} onToggle={() => toggleNotif(i)} label={n.label} />
              </label>
            ))}
          </div>
        </Card>
        {/* Account */}
        <Card>
          <CardHeader title="Account" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { label: "Connected accounts · GitHub, Coursera", danger: false },
              { label: "Two-factor authentication · enabled", danger: false },
              { label: "Change password", danger: false },
              { label: "Deactivate account", danger: true },
            ].map((b) => (
              <Btn key={b.label} ghost style={{ justifyContent: "flex-start", width: "100%", color: b.danger ? "var(--rose)" : "var(--ink-2)", borderColor: b.danger ? "color-mix(in srgb,var(--rose) 25%,transparent)" : "var(--line-2)" }}
                onClick={() => show(`${b.label} — coming soon.`)}
              >
                {b.label}
              </Btn>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ── PRIVACY ── */
export function StudentPrivacy() {
  const { show, msg } = useDemoToast();

  const [recruiterDiscovery, setRecruiterDiscovery] = useState([
    { label: "Discoverable in search", sub: "Verified recruiters can find your profile", on: true },
    { label: "Show real name", sub: "Off → recruiters see initials until invite", on: true },
    { label: "Show GPA", sub: "Recommended off · GPA bias risk", on: false },
  ]);

  const [visaDisclosure, setVisaDisclosure] = useState([
    { label: "Show F-1 status to F-1-OK employers", on: true },
    { label: "Show F-1 status to all employers", on: false },
  ]);

  const [skillEvidence, setSkillEvidence] = useState([
    { label: "Public GitHub repos", sub: "Visible to recruiters · 12 repos", on: true },
    { label: "Coursework / transcripts", sub: "Course names & grades · 4 visible", on: true },
    { label: "Live deployed projects", sub: "project-flux.app · 2 others", on: true },
    { label: "Certifications", sub: "AWS · Meta React · 2 others", on: true },
  ]);

  const toggleRecruiter = (i: number) => {
    setRecruiterDiscovery(prev => {
      const next = [...prev];
      next[i] = { ...next[i], on: !next[i].on };
      show(`${next[i].label}: ${next[i].on ? "enabled" : "disabled"}`);
      return next;
    });
  };

  const toggleVisa = (i: number) => {
    setVisaDisclosure(prev => {
      const next = [...prev];
      next[i] = { ...next[i], on: !next[i].on };
      show(`${next[i].label}: ${next[i].on ? "enabled" : "disabled"}`);
      return next;
    });
  };

  const toggleSkill = (i: number) => {
    setSkillEvidence(prev => {
      const next = [...prev];
      next[i] = { ...next[i], on: !next[i].on };
      show(`${next[i].label}: ${next[i].on ? "enabled" : "disabled"}`);
      return next;
    });
  };

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Account · Privacy"
        title="You control what's visible."
        lede="VeriBridge AI's privacy is opt-in by default. Recruiters and universities only see fields you've explicitly approved."
      />
      {/* Privacy banner */}
      <div
        style={{
          background: "linear-gradient(135deg,var(--emerald-soft),var(--purple-soft))",
          border: "1px solid color-mix(in srgb,var(--emerald) 22%,transparent)",
          borderRadius: 13,
          padding: "18px 20px",
          display: "grid",
          gridTemplateColumns: "auto 1fr auto",
          gap: 16,
          alignItems: "center",
          marginBottom: 18,
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: "#fff",
            color: "var(--emerald)",
            display: "grid",
            placeItems: "center",
            fontWeight: 700,
            fontSize: 18,
            border: "1px solid color-mix(in srgb,var(--emerald) 25%,transparent)",
          }}
        >
          🛡
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, letterSpacing: "-0.005em" }}>Opt-in privacy is on.</div>
          <div style={{ fontSize: 12, color: "var(--ink-2)", marginTop: 2, lineHeight: 1.5 }}>
            Your visa status, GPA, and contact info are private by default. WPI sees aggregate cohort data only — never individual profiles.
          </div>
        </div>
        <Mono style={{ fontSize: 11, letterSpacing: "0.12em", color: "var(--emerald)", textTransform: "uppercase", fontWeight: 700 }}>
          Compliant ✓
        </Mono>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Recruiter discovery */}
        <Card>
          <CardHeader title="Recruiter discovery" eyebrow="● ON" />
          <div style={{ display: "flex", flexDirection: "column" }}>
            {recruiterDiscovery.map((n, i) => (
              <label key={n.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 0", borderBottom: i < recruiterDiscovery.length - 1 ? "1px solid var(--line)" : "none", cursor: "pointer" }}>
                <span>
                  <b style={{ fontSize: 13 }}>{n.label}</b>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{n.sub}</div>
                </span>
                <Toggle on={n.on} onToggle={() => toggleRecruiter(i)} label={n.label} />
              </label>
            ))}
          </div>
        </Card>
        {/* Visa status disclosure */}
        <Card>
          <CardHeader title="Visa status disclosure" eyebrow="Default private" />
          <p style={{ fontSize: 13, color: "var(--ink-2)", lineHeight: 1.55, margin: "0 0 12px" }}>
            Visa status is hidden until you opt in <em>per company</em>. Recruiters can filter by F-1 OK only against the consenting pool — never the full graph.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {visaDisclosure.map((n, i) => (
              <label key={n.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px", background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 8, cursor: "pointer" }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{n.label}</span>
                <Toggle on={n.on} onToggle={() => toggleVisa(i)} label={n.label} />
              </label>
            ))}
          </div>
        </Card>
        {/* Skill evidence visibility */}
        <Card>
          <CardHeader title="Skill evidence visibility" eyebrow="18 verified" />
          <div style={{ display: "flex", flexDirection: "column" }}>
            {skillEvidence.map((n, i) => (
              <label key={n.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "11px 0", borderBottom: i < skillEvidence.length - 1 ? "1px solid var(--line)" : "none", cursor: "pointer" }}>
                <span>
                  <b style={{ fontSize: 13 }}>{n.label}</b>
                  <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{n.sub}</div>
                </span>
                <Toggle on={n.on} onToggle={() => toggleSkill(i)} label={n.label} />
              </label>
            ))}
          </div>
        </Card>
        {/* Data & consent */}
        <Card>
          <CardHeader title="Data & consent" eyebrow="FERPA-aware" />
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { label: "↓ Download my data · ZIP", danger: false },
              { label: "⊟ View consent log · 23 events", danger: false },
              { label: "◇ Manage university data sharing", danger: false },
              { label: "▭ Audit log · who viewed my profile", danger: false },
            ].map((b) => (
              <Btn key={b.label} ghost style={{ justifyContent: "flex-start", width: "100%" }}
                onClick={() => show(`${b.label} — coming soon.`)}
              >
                {b.label}
              </Btn>
            ))}
            <div style={{ height: 1, background: "var(--line)", margin: "6px 0" }} />
            <Btn ghost style={{ justifyContent: "flex-start", width: "100%", color: "var(--rose)", borderColor: "color-mix(in srgb,var(--rose) 25%,transparent)" }}
              onClick={() => show("Account deletion requires confirmation — coming soon.")}
            >
              ⊘ Delete account &amp; all data
            </Btn>
          </div>
        </Card>
      </div>
    </div>
  );
}
