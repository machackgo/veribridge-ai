"use client";

/**
 * Skill Gaps — real, evidence-derived surface.
 *
 * Every item on this page is computed deterministically from the user's own
 * stored evidence (claimed skills, canonical skill claims + evidence links,
 * completed website workflow analyses). Nothing here is sample data: there
 * are no fabricated jobs, salaries, market percentages, or readiness scores,
 * and when the evidence cannot support an assessment the page says so
 * instead of guessing.
 */

import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import {
  evidenceBasisHref,
  getSkillGapsOverview,
  type ProjectSkillGapReport,
  type SkillGapItem,
  type SkillGapStatus,
  type SkillGapsOverviewResponse,
} from "@/lib/skill-gaps-api";

/* ── Small local primitives (dashboard visual idiom, no mock imports) ── */

function Mono({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <span style={{ fontFamily: "'JetBrains Mono', monospace", ...style }}>{children}</span>
  );
}

function Card({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background: "var(--bg-1, var(--bg))",
        border: "1px solid var(--line)",
        borderRadius: 14,
        padding: 18,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

const STATUS_STYLE: Record<SkillGapStatus, { color: string; bg: string; border: string }> = {
  missing_evidence: { color: "#9f1239", bg: "#fff1f2", border: "#fecdd3" },
  insufficient_evidence: { color: "#92400e", bg: "#fffbeb", border: "#fde68a" },
  partially_demonstrated: { color: "#3730a3", bg: "#eef2ff", border: "#c7d2fe" },
  not_assessed: { color: "#475569", bg: "#f8fafc", border: "#e2e8f0" },
};

function StatusBadge({ item }: { item: SkillGapItem }) {
  const s = STATUS_STYLE[item.status] ?? STATUS_STYLE.not_assessed;
  return (
    <Mono
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        padding: "4px 9px",
        borderRadius: 999,
        color: s.color,
        background: s.bg,
        border: `1px solid ${s.border}`,
        whiteSpace: "nowrap",
      }}
    >
      {item.status_label}
    </Mono>
  );
}

/* ── Gap item card ── */

function GapItemCard({ item }: { item: SkillGapItem }) {
  const s = STATUS_STYLE[item.status] ?? STATUS_STYLE.not_assessed;
  return (
    <div
      data-testid="skill-gap-item"
      style={{
        border: "1px solid var(--line)",
        borderLeft: `3px solid ${s.border}`,
        borderRadius: 10,
        padding: 14,
        background: "var(--bg-2)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>{item.skill_name}</div>
        <StatusBadge item={item} />
      </div>

      <p style={{ margin: 0, fontSize: 12.5, color: "var(--ink-2)", lineHeight: 1.55 }}>{item.why}</p>

      {item.evidence_basis.length > 0 && (
        <div>
          <Mono style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)" }}>
            Evidence basis
          </Mono>
          <ul style={{ margin: "5px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
            {item.evidence_basis.map((entry, i) => {
              const href = evidenceBasisHref(entry);
              const meta = [
                entry.proof_type,
                entry.citation_type,
                entry.link_status,
                entry.evidence_quality,
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <li key={`${entry.reference_id || entry.kind}-${i}`} style={{ fontSize: 11.5, color: "var(--ink-2)", lineHeight: 1.5, display: "flex", gap: 6, alignItems: "baseline", flexWrap: "wrap" }}>
                  <span style={{ color: "var(--muted)", flexShrink: 0 }}>○</span>
                  <span>
                    {entry.detail}
                    {meta && (
                      <Mono style={{ fontSize: 10, color: "var(--muted)", marginLeft: 6 }}>[{meta}]</Mono>
                    )}
                    {entry.limitations.length > 0 && (
                      <span style={{ color: "var(--muted)" }}> — {entry.limitations.join(" ")}</span>
                    )}
                    {href && (
                      <Link href={href} style={{ marginLeft: 6, fontSize: 11, color: "var(--indigo)" }}>
                        View evidence →
                      </Link>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div
        style={{
          fontSize: 12,
          color: "var(--ink-2)",
          background: "var(--bg-1, var(--bg))",
          border: "1px dashed var(--line)",
          borderRadius: 8,
          padding: "8px 10px",
          lineHeight: 1.55,
        }}
      >
        <Mono style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", display: "block", marginBottom: 3 }}>
          Recommended next proof
        </Mono>
        {item.recommended_action}
      </div>
    </div>
  );
}

/* ── Project report section ── */

function ProjectReport({ report }: { report: ProjectSkillGapReport }) {
  if (report.assessment_state === "insufficient_evidence") {
    return (
      <Card>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>Not enough evidence to assess</div>
        <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
          {report.insufficient_evidence_note}
        </p>
      </Card>
    );
  }

  const counts = report.summary;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <Mono style={{ fontSize: 11, color: "var(--muted)" }}>
            {counts.total_claimed} claimed · {counts.demonstrated} demonstrated ·{" "}
            {counts.partially_demonstrated} partially · {counts.insufficient_evidence} insufficient ·{" "}
            {counts.missing_evidence} missing · {counts.not_assessed} not assessed
          </Mono>
          <Link
            href={`/student/vbr/projects/${encodeURIComponent(report.project_id)}/report`}
            style={{ fontSize: 12, color: "var(--indigo)" }}
          >
            Open project report →
          </Link>
        </div>
        {report.demonstrated_skills.length > 0 && (
          <div style={{ marginTop: 10, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <Mono style={{ fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)" }}>
              Demonstrated
            </Mono>
            {report.demonstrated_skills.map((skill) => (
              <span
                key={skill}
                style={{ fontSize: 11, padding: "3px 9px", borderRadius: 999, background: "#ecfdf5", color: "#065f46", border: "1px solid #a7f3d0" }}
              >
                {skill}
              </span>
            ))}
          </div>
        )}
      </Card>

      {report.gap_items.length === 0 ? (
        <Card>
          <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)" }}>
            No gaps: every assessed skill on this project is demonstrated.
          </p>
        </Card>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {report.gap_items.map((item) => (
            <GapItemCard key={item.skill_key} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Page ── */

export default function Page() {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "error"; message: string }
    | { kind: "ready"; data: SkillGapsOverviewResponse }
  >({ kind: "loading" });
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    getSkillGapsOverview()
      .then((data) => {
        if (cancelled) return;
        setState({ kind: "ready", data });
        setSelectedProjectId((current) =>
          current && data.projects.some((p) => p.project_id === current)
            ? current
            : data.projects[0]?.project_id ?? null,
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: error instanceof Error ? error.message : "Failed to load skill gaps.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <Mono style={{ fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: "var(--muted)" }}>
          Dashboard · Skill Gaps
        </Mono>
        <h1 style={{ margin: "6px 0 6px", fontSize: 26, fontWeight: 650, letterSpacing: "-0.02em", color: "var(--ink)" }}>
          Skill gaps, from your evidence.
        </h1>
        <p style={{ margin: 0, fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.6, maxWidth: 640 }}>
          Derived deterministically from what your projects claim and what your attached proofs
          actually demonstrate. No market estimates, no AI guesses — when the evidence is not
          enough to assess a skill, it says so.
        </p>
      </div>

      {state.kind === "loading" && (
        <Card>
          <p style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>Loading your evidence…</p>
        </Card>
      )}

      {state.kind === "error" && (
        <Card>
          <p role="alert" style={{ margin: "0 0 10px", fontSize: 13, color: "#9f1239" }}>{state.message}</p>
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            style={{
              fontSize: 12,
              fontWeight: 600,
              padding: "7px 14px",
              borderRadius: 8,
              border: "1px solid var(--line)",
              background: "var(--bg-2)",
              color: "var(--ink)",
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </Card>
      )}

      {state.kind === "ready" && state.data.projects.length === 0 && (
        <Card>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No projects yet</div>
          <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)", lineHeight: 1.6 }}>
            Skill gaps are computed per project from your attached evidence. Create a project and
            attach proofs to see an honest assessment here.{" "}
            <Link href="/student" style={{ color: "var(--indigo)" }}>
              Go to Student Dashboard →
            </Link>
          </p>
        </Card>
      )}

      {state.kind === "ready" && state.data.projects.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {state.data.projects.map((project) => {
              const selected = project.project_id === selectedProjectId;
              return (
                <button
                  key={project.project_id}
                  type="button"
                  onClick={() => setSelectedProjectId(project.project_id)}
                  style={{
                    fontSize: 12.5,
                    fontWeight: 600,
                    padding: "8px 14px",
                    borderRadius: 999,
                    cursor: "pointer",
                    border: selected ? "1px solid var(--indigo)" : "1px solid var(--line)",
                    background: selected ? "var(--indigo-soft, #eef2ff)" : "var(--bg-2)",
                    color: selected ? "var(--indigo)" : "var(--ink-2)",
                  }}
                >
                  {project.project_title}
                  <Mono style={{ fontSize: 10, marginLeft: 7, color: "var(--muted)" }}>
                    {project.assessment_state === "insufficient_evidence"
                      ? "no evidence"
                      : `${project.gap_items.length} gap${project.gap_items.length === 1 ? "" : "s"}`}
                  </Mono>
                </button>
              );
            })}
          </div>

          {(() => {
            const report = state.data.projects.find((p) => p.project_id === selectedProjectId);
            return report ? <ProjectReport report={report} /> : null;
          })()}
        </div>
      )}
    </div>
  );
}
