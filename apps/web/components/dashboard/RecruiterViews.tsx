"use client";

import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { DemoToast, useDemoToast } from "../ui/DemoToast";
import { EvidenceAccessActions } from "../skill-proof/evidence-access-actions";
import { ProjectEvidenceActions } from "../skill-proof/project-evidence-actions";
import {
  buildRecruiterProofArtifacts,
  buildRecruiterProjectEvidenceBundles,
  type RecruiterProofArtifact,
  type RecruiterProjectEvidenceBundle,
  isRealSubmittedProofEvidence,
} from "../skill-proof/recruiter-project-proof-adapter";
import { getProofVisibilityLabel } from "../onboarding/taxonomy";
import { getLatestEvidenceAccessLinks, listSkillEvidence, searchRecruiterCandidates, fetchRecruiterCandidateDetail, type CandidateSearchResponse, type CandidateSearchResult, type EvidenceAccessLink, type EvidenceAccessLinkItem, type RecruiterCandidateDetailResponse, type SkillEvidenceResponse } from "@/lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────

function PageHeader({
  crumb,
  title,
  lede,
  action,
}: {
  crumb: string;
  title: ReactNode;
  lede: string;
  action?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 20 }}>
      <div>
        <div
          style={{
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 11,
            letterSpacing: "0.16em",
            color: "var(--muted)",
            textTransform: "uppercase",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--emerald)",
              display: "inline-block",
              animation: "recruiter-pulse 2s infinite",
            }}
          />
          {crumb}
        </div>
        <h1
          style={{
            fontSize: 32,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            margin: "4px 0 4px",
            color: "var(--ink)",
          }}
        >
          {title}
        </h1>
        <p style={{ fontSize: 14, color: "var(--muted)", margin: 0, maxWidth: 680 }}>{lede}</p>
      </div>
      {action && <div style={{ display: "flex", gap: 8 }}>{action}</div>}
    </div>
  );
}

const card: React.CSSProperties = {
  background: "var(--paper)",
  border: "1px solid var(--line)",
  borderRadius: 14,
  padding: 20,
};

function Btn({ children, variant = "primary", style: extraStyle, onClick, ...rest }: {
  children: ReactNode;
  variant?: "primary" | "secondary";
  style?: React.CSSProperties;
  onClick?: () => void;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "9px 16px",
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    border: "1px solid",
    textDecoration: "none",
  };
  const styles: React.CSSProperties =
    variant === "primary"
      ? { ...base, background: "var(--ink)", color: "#fff", borderColor: "transparent" }
      : { ...base, background: "transparent", color: "var(--ink-2)", borderColor: "var(--line)" };
  return (
    <button type="button" onClick={onClick} style={{ ...styles, ...extraStyle }} {...rest}>
      {children}
    </button>
  );
}

function FilterChip({ children, active }: { children: ReactNode; active?: boolean }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "4px 10px",
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 500,
        background: active ? "var(--indigo-soft)" : "var(--bg-2)",
        color: active ? "var(--indigo)" : "var(--ink-2)",
        border: `1px solid ${active ? "#c7d2fe" : "var(--line)"}`,
        cursor: "pointer",
      }}
    >
      {active && <span style={{ color: "var(--indigo)", fontWeight: 700 }}>×</span>}
      {children}
    </span>
  );
}

// ── Recruiter search state ─────────────────────────────────────────────────

type RecruiterSearchState =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "done"; query: string; results: CandidateSearchResult[] }
  | { status: "error"; query: string; error: string }

// ── Candidate detail fetch state ───────────────────────────────────────────

type DetailFetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; detail: RecruiterCandidateDetailResponse }
  | { status: "error"; error: string }

// ── Search result candidate card ───────────────────────────────────────────

function SearchResultCandidateCard({
  result,
  selected,
  onClick,
}: {
  result: CandidateSearchResult
  selected: boolean
  onClick: () => void
}) {
  const schoolLine = [result.school_name, result.degree, result.major]
    .filter(Boolean)
    .join(" · ")

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onClick()}
      data-testid={`search-result-card-${result.user_id}`}
      style={{
        display: "grid",
        gap: 10,
        padding: "14px 16px",
        borderRadius: 12,
        background: selected ? "var(--indigo-soft)" : "var(--bg-2)",
        border: `1px solid ${selected ? "#c7d2fe" : "var(--line)"}`,
        cursor: "pointer",
        marginBottom: 8,
        outline: "none",
      }}
    >
      {/* Name row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, color: "var(--ink)", marginBottom: 2 }}>
            {result.display_name}
          </div>
          {schoolLine && (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>{schoolLine}</div>
          )}
        </div>
        {/* Proof status badge */}
        <span
          style={{
            flexShrink: 0,
            fontSize: 10,
            fontWeight: 700,
            padding: "3px 8px",
            borderRadius: 5,
            background: result.accepted_evidence_count > 0 ? "var(--emerald-soft)" : "var(--bg-2)",
            color: result.accepted_evidence_count > 0 ? "#065f46" : "var(--muted)",
            border: `1px solid ${result.accepted_evidence_count > 0 ? "#6ee7b7" : "var(--line)"}`,
            fontFamily: "'JetBrains Mono',monospace",
          }}
        >
          {result.proof_status_label ?? "Pending Analysis"}
        </span>
      </div>

      {/* Matched skills */}
      <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
        {result.matched_skill_names.slice(0, 4).map((s) => (
          <span
            key={s}
            style={{
              fontSize: 11,
              padding: "2px 7px",
              borderRadius: 4,
              background: "var(--indigo-soft)",
              color: "var(--indigo)",
              fontWeight: 500,
            }}
          >
            {s}
          </span>
        ))}
        {result.matched_skill_names.length > 4 && (
          <span style={{ fontSize: 11, color: "var(--muted)", alignSelf: "center" }}>
            +{result.matched_skill_names.length - 4} more
          </span>
        )}
      </div>

      {/* Project + proof type badges */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {result.strongest_project_title && (
          <span style={{ fontSize: 11, color: "var(--ink-2)", fontWeight: 500, flexShrink: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 260 }}>
            {result.strongest_project_title}
          </span>
        )}
        <span style={{ marginLeft: "auto", display: "flex", gap: 5, flexShrink: 0 }}>
          {result.has_github_proof && (
            <span
              title="GitHub proof available"
              style={{
                fontSize: 10,
                padding: "2px 6px",
                borderRadius: 4,
                background: "#f3f4f6",
                color: "#374151",
                fontWeight: 600,
                border: "1px solid #e5e7eb",
              }}
            >
              ⌥ GitHub
            </span>
          )}
          {result.has_website_proof && (
            <span
              title="Live website proof available"
              style={{
                fontSize: 10,
                padding: "2px 6px",
                borderRadius: 4,
                background: "#f0fdf4",
                color: "#166534",
                fontWeight: 600,
                border: "1px solid #bbf7d0",
              }}
            >
              ▤ Live site
            </span>
          )}
        </span>
      </div>

      {/* Evidence count */}
      <div style={{ fontSize: 11, color: "var(--muted)" }}>
        {result.evidence_count} evidence {result.evidence_count === 1 ? "source" : "sources"} · {result.accepted_evidence_count} accepted
      </div>
    </div>
  )
}

// ── Search result detail panel (Phase J2) ─────────────────────────────────

function DetailProofProjectCard({ project }: { project: import("@/lib/api").ProofProjectSummary }) {
  const availableLinks = project.evidence_access_links.filter(
    (link) => link.availability_status === "available" && link.url
  )
  const githubCount = availableLinks.filter((l) => l.access_type === "github_exact_lines").length

  function buildLinkLabel(link: EvidenceAccessLinkItem): string {
    if (link.access_type === "live_website") return link.label || "Open Live Website"
    if (
      typeof link.line_start === "number" &&
      typeof link.line_end === "number" &&
      githubCount > 1
    ) {
      return link.line_start === link.line_end
        ? `View Code Line ${link.line_start}`
        : `View Code Lines ${link.line_start}–${link.line_end}`
    }
    return link.label || "View Exact Code Lines"
  }

  return (
    <div
      data-testid={`detail-proof-project-${project.project_title.replace(/\s+/g, "-").toLowerCase()}`}
      style={{
        border: "1px solid var(--line)",
        borderRadius: 10,
        background: "var(--bg-2)",
        padding: 12,
        display: "grid",
        gap: 8,
      }}
    >
      {/* Project header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ fontWeight: 700, fontSize: 13, color: "var(--ink)", lineHeight: 1.3 }}>
          {project.project_title}
        </div>
        {project.status_label && (
          <span
            style={{
              flexShrink: 0,
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 7px",
              borderRadius: 4,
              background: project.status_code === "verified" ? "var(--emerald-soft)" : "var(--bg-2)",
              color: project.status_code === "verified" ? "#065f46" : "var(--muted)",
              border: `1px solid ${project.status_code === "verified" ? "#6ee7b7" : "var(--line)"}`,
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            {project.status_label}
          </span>
        )}
      </div>

      {/* Skill tags */}
      {project.associated_skill_labels.length > 0 && (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {project.associated_skill_labels.map((s) => (
            <span
              key={s}
              style={{
                fontSize: 10,
                padding: "2px 6px",
                borderRadius: 4,
                background: "var(--indigo-soft)",
                color: "var(--indigo)",
                fontWeight: 500,
              }}
            >
              {s}
            </span>
          ))}
        </div>
      )}

      {/* Recruiter summary */}
      {project.recruiter_summary && (
        <div style={{ fontSize: 11, color: "var(--ink-2)", lineHeight: 1.5 }}>
          {project.recruiter_summary}
        </div>
      )}

      {/* Evidence type badges */}
      <div style={{ display: "flex", gap: 5 }}>
        {project.has_github_proof && (
          <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "#f3f4f6", color: "#374151", fontWeight: 600, border: "1px solid #e5e7eb" }}>
            ⌥ GitHub
          </span>
        )}
        {project.has_website_proof && (
          <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 4, background: "#f0fdf4", color: "#166534", fontWeight: 600, border: "1px solid #bbf7d0" }}>
            ▤ Live site
          </span>
        )}
      </div>

      {/* Access links */}
      {availableLinks.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {availableLinks.map((link) => (
            <a
              key={link.id}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              data-testid={`detail-evidence-link-${link.id}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "7px 11px",
                borderRadius: 7,
                border: "1px solid var(--line)",
                background: "#fff",
                color: "var(--ink)",
                fontSize: 12,
                fontWeight: 600,
                textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              {buildLinkLabel(link)}
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function SearchResultDetailPanel({
  result,
  detailState,
}: {
  result: CandidateSearchResult
  detailState: DetailFetchState
}) {
  const schoolLine = [result.school_name, result.degree, result.major].filter(Boolean).join(" · ")
  const detail = detailState.status === "done" ? detailState.detail : null

  const overviewStats = detail
    ? [
        { label: "Total evidence", value: String(detail.proof_overview.total_evidence_count) },
        { label: "Accepted", value: String(detail.proof_overview.accepted_evidence_count) },
        { label: "GitHub proof", value: String(detail.proof_overview.github_proof_count) },
        { label: "Live site proof", value: String(detail.proof_overview.website_proof_count) },
      ]
    : [
        { label: "Evidence sources", value: String(result.evidence_count) },
        { label: "Accepted", value: String(result.accepted_evidence_count) },
        { label: "GitHub proof", value: result.has_github_proof ? "Yes" : "None" },
        { label: "Live site proof", value: result.has_website_proof ? "Yes" : "None" },
      ]

  return (
    <div style={{ ...card, position: "sticky", top: 100, alignSelf: "start" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: "50%",
            background: "linear-gradient(135deg,#6366f1,#8b5cf6)",
            display: "grid",
            placeItems: "center",
            fontWeight: 700,
            fontSize: 16,
            color: "#fff",
            flexShrink: 0,
          }}
        >
          {result.display_name.charAt(0).toUpperCase()}
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>{result.display_name}</div>
          {schoolLine && <div style={{ fontSize: 12, color: "var(--muted)" }}>{schoolLine}</div>}
          <span
            style={{
              display: "inline-block",
              marginTop: 4,
              fontSize: 10,
              fontWeight: 600,
              padding: "2px 7px",
              borderRadius: 4,
              background: result.accepted_evidence_count > 0 ? "var(--emerald-soft)" : "var(--bg-2)",
              color: result.accepted_evidence_count > 0 ? "#065f46" : "var(--muted)",
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            {result.proof_status_label ?? "Pending Analysis"}
          </span>
        </div>
      </div>

      {/* Proof overview stats */}
      <div
        data-testid="detail-proof-overview"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}
      >
        {overviewStats.map(({ label, value }) => (
          <div
            key={label}
            style={{ background: "var(--bg-2)", borderRadius: 8, padding: "10px 12px", textAlign: "center" }}
          >
            <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 600, marginBottom: 4 }}>{label}</div>
            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Loading state */}
      {detailState.status === "loading" && (
        <div style={{ fontSize: 12, color: "var(--muted)", display: "flex", alignItems: "center", gap: 8, marginBottom: 14, padding: "10px 12px", background: "var(--bg-2)", borderRadius: 8 }}>
          <span
            data-testid="detail-loading-indicator"
            style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: "var(--indigo)", animation: "recruiter-pulse 1.2s infinite" }}
          />
          Loading candidate proof detail…
        </div>
      )}

      {/* Error state */}
      {detailState.status === "error" && (
        <div
          data-testid="detail-error-message"
          style={{ fontSize: 12, color: "var(--muted)", marginBottom: 14, padding: "10px 12px", background: "var(--bg-2)", borderRadius: 8, border: "1px solid var(--line)" }}
        >
          Could not load full proof detail: {detailState.error}
        </div>
      )}

      {/* Verified/supported skills from detail */}
      {detail && detail.verified_or_supported_skills.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>Verified Skills</div>
          <div style={{ marginBottom: 14 }}>
            {detail.verified_or_supported_skills.map((s) => (
              <div
                key={s.skill_name}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "7px 0", borderBottom: "1px solid var(--line)", fontSize: 12, color: "var(--ink-2)" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ color: "var(--emerald)", fontWeight: 700 }}>✓</span>
                  {s.skill_name}
                </div>
                <span style={{ fontSize: 10, color: "var(--muted)" }}>{s.evidence_count} {s.evidence_count === 1 ? "source" : "sources"}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Matched skills fallback (before detail loads) */}
      {!detail && detailState.status !== "loading" && result.matched_skill_names.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>Matched Skills</div>
          <div style={{ marginBottom: 14 }}>
            {result.matched_skill_names.map((s) => (
              <div key={s} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 0", borderBottom: "1px solid var(--line)", fontSize: 12, color: "var(--ink-2)" }}>
                <span style={{ color: "var(--emerald)", fontWeight: 700 }}>✓</span>
                {s}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Proof projects from detail */}
      {detail && detail.proof_projects.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>Project Evidence</div>
          <div data-testid="detail-proof-projects" style={{ display: "grid", gap: 8, marginBottom: 14 }}>
            {detail.proof_projects.map((project) => (
              <DetailProofProjectCard key={project.project_title} project={project} />
            ))}
          </div>
        </>
      )}

      {/* Sparse/no-proof state from detail */}
      {detail && detail.proof_projects.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--muted)", padding: "10px 12px", background: "var(--bg-2)", borderRadius: 8, marginBottom: 14 }}>
          No proof projects found for this candidate yet.
        </div>
      )}
    </div>
  )
}

function SwitchRow({
  label,
  sub,
  defaultOn = true,
  onToast,
}: {
  label: string;
  sub?: string;
  defaultOn?: boolean;
  onToast?: (msg: string) => void;
}) {
  const [on, setOn] = useState(defaultOn);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 12px",
        borderRadius: 8,
        background: "var(--bg-2)",
        marginBottom: 6,
        gap: 12,
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink-2)" }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>{sub}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={label}
        onClick={() => {
          const next = !on;
          setOn(next);
          onToast?.(`${label}: ${next ? "enabled" : "disabled"}`);
        }}
        style={{
          width: 38,
          height: 22,
          borderRadius: 99,
          background: on ? "var(--emerald, #10b981)" : "var(--line, #e6e8ef)",
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
    </div>
  );
}

// ── Candidate data ─────────────────────────────────────────────────────────

const candidates = [
  {
    initials: "MR",
    grad: "linear-gradient(135deg,#6366f1,#8b5cf6)",
    name: "Maya Reyes",
    school: "WPI · CS '26",
    skills: ["Docker", "React", "Distributed Sys"],
    visa: "F-1 OK",
    visaTone: "indigo",
    score: 94,
  },
  {
    initials: "JK",
    grad: "linear-gradient(135deg,#0ea5e9,#6366f1)",
    name: "Jordan Kim",
    school: "MIT · EECS '26",
    skills: ["Python", "ML/Data", "Kubernetes"],
    visa: "US Citizen",
    visaTone: "emerald",
    score: 91,
  },
  {
    initials: "AS",
    grad: "linear-gradient(135deg,#f59e0b,#ef4444)",
    name: "Arjun Singh",
    school: "CMU · SCS '26",
    skills: ["Go", "System Design", "Postgres"],
    visa: "F-1 OK",
    visaTone: "indigo",
    score: 88,
  },
  {
    initials: "LP",
    grad: "linear-gradient(135deg,#10b981,#0ea5e9)",
    name: "Leila Pham",
    school: "Stanford · CS '26",
    skills: ["TypeScript", "GraphQL", "AWS"],
    visa: "US Citizen",
    visaTone: "emerald",
    score: 86,
  },
];

// ── Candidate list ─────────────────────────────────────────────────────────

function CandidateList() {
  return (
    <div style={{ borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)" }}>
      {candidates.map((c, i) => (
        <div
          key={c.name}
          style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr auto auto auto",
            gap: 14,
            padding: "14px 12px",
            borderBottom: i < candidates.length - 1 ? "1px solid var(--line)" : "none",
            alignItems: "center",
            cursor: "pointer",
            transition: "background 0.12s",
          }}
          className="recruiter-row-hover"
        >
          {/* Avatar */}
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: "50%",
              background: c.grad,
              display: "grid",
              placeItems: "center",
              fontWeight: 600,
              fontSize: 13,
              color: "#fff",
              flexShrink: 0,
            }}
          >
            {c.initials}
          </div>
          {/* Name + school + skills */}
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)", marginBottom: 2 }}>{c.name}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 5 }}>{c.school}</div>
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {c.skills.map((s) => (
                <span
                  key={s}
                  style={{
                    fontSize: 11,
                    padding: "2px 7px",
                    borderRadius: 4,
                    background: "var(--indigo-soft)",
                    color: "var(--indigo)",
                    fontWeight: 500,
                  }}
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
          {/* Visa badge */}
          <span
            style={{
              fontFamily: "'JetBrains Mono',monospace",
              fontSize: 10,
              padding: "3px 7px",
              borderRadius: 5,
              background: c.visaTone === "indigo" ? "var(--indigo-soft)" : "var(--emerald-soft)",
              color: c.visaTone === "indigo" ? "var(--indigo)" : "#065f46",
              fontWeight: 600,
              whiteSpace: "nowrap",
            }}
          >
            {c.visa}
          </span>
          {/* Score */}
          <div style={{ textAlign: "right" }}>
            <div
              style={{
                fontFamily: "'JetBrains Mono',monospace",
                fontSize: 18,
                fontWeight: 700,
                color: "var(--indigo)",
              }}
            >
              {c.score}
            </div>
            <div style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Match</div>
          </div>
          {/* Arrow */}
          <span style={{ color: "var(--muted)", fontSize: 16 }}>→</span>
        </div>
      ))}
    </div>
  );
}

// ── Candidate preview ──────────────────────────────────────────────────────

function CandidatePreview({ onToast }: { onToast?: (msg: string) => void }) {
  const [activeEvidenceIndex, setActiveEvidenceIndex] = useState(-1);
  const [realProofData, setRealProofData] = useState<{
    loading: boolean;
    bundles: RecruiterProjectEvidenceBundle[];
    artifacts: RecruiterProofArtifact[];
    error: string | null;
  }>({
    loading: true,
    bundles: [],
    artifacts: [],
    error: null,
  });

  useEffect(() => {
    let active = true;

    async function loadRealProofData() {
      try {
        const evidenceRows = await listSkillEvidence();
        const realEvidenceRows = evidenceRows.filter(isRealSubmittedProofEvidence);
        const accessLinksByEvidenceId = new Map<string, EvidenceAccessLink[]>();

        await Promise.all(
          realEvidenceRows.map(async (evidence) => {
            try {
              const links = await getLatestEvidenceAccessLinks(evidence.id);
              accessLinksByEvidenceId.set(evidence.id, links);
            } catch {
              accessLinksByEvidenceId.set(evidence.id, []);
            }
          })
        );

        if (!active) return;

        setRealProofData({
          loading: false,
          bundles: buildRecruiterProjectEvidenceBundles(realEvidenceRows, accessLinksByEvidenceId),
          artifacts: buildRecruiterProofArtifacts(realEvidenceRows, accessLinksByEvidenceId),
          error: null,
        });
      } catch (error) {
        if (!active) return;
        setRealProofData({
          loading: false,
          bundles: [],
          artifacts: [],
          error: error instanceof Error ? error.message : "Unable to load real proof data.",
        });
      }
    }

    loadRealProofData();

    return () => {
      active = false;
    };
  }, []);

  const maya = candidates[0];
  const paStats = [
    { label: "VeriBridge", value: "82" },
    { label: "Match", value: "94%" },
    { label: "Verified Skills", value: "18" },
    { label: "Visa", value: "F-1 OK" },
  ];
  const skills = ["Docker · Production app · 3 sources", "Distributed Systems · A · WPI transcript", "React + TypeScript · 5 evidence", "Kubernetes · cert + coursework"];
  const githubProofAccessLinks: EvidenceAccessLink[] = [
    {
      id: "demo-github-access-20-32",
      evidence_id: "demo-github-evidence",
      source_report_type: "github_recruiter_proof_report",
      source_report_id: "demo-github-report",
      access_type: "github_exact_lines",
      label: "View Exact Code Lines",
      url: "https://github.com/maya/proof-app/blob/main/app/main.py#L20-L32",
      source_type: "github",
      file_path: "app/main.py",
      line_start: 20,
      line_end: 32,
      availability_status: "available",
      notes: "Decision Tree training segment from the recruiter report.",
      created_at: "2026-05-19T00:00:00.000Z",
      updated_at: "2026-05-19T00:00:00.000Z",
    },
    {
      id: "demo-github-access-52-61",
      evidence_id: "demo-github-evidence",
      source_report_type: "github_recruiter_proof_report",
      source_report_id: "demo-github-report",
      access_type: "github_exact_lines",
      label: "View Exact Code Lines",
      url: "https://github.com/maya/proof-app/blob/main/app/main.py#L52-L61",
      source_type: "github",
      file_path: "app/main.py",
      line_start: 52,
      line_end: 61,
      availability_status: "available",
      notes: "Evaluation metrics segment from the recruiter report.",
      created_at: "2026-05-19T00:00:00.000Z",
      updated_at: "2026-05-19T00:00:00.000Z",
    },
  ];
  const websiteProofAccessLinks: EvidenceAccessLink[] = [
    {
      id: "demo-website-access-live",
      evidence_id: "demo-website-evidence",
      source_report_type: "website_semantic_verification_result",
      source_report_id: "demo-website-report",
      access_type: "live_website",
      label: "Open Live Website",
      url: "https://student-app.example.com",
      source_type: "website",
      file_path: null,
      line_start: null,
      line_end: null,
      availability_status: "available",
      notes: "Public deployed proof inspected through the semantic verification report.",
      created_at: "2026-05-19T00:00:00.000Z",
      updated_at: "2026-05-19T00:00:00.000Z",
    },
  ];
  const projectEvidenceBundles = [
    {
      id: "combined-project",
      projectName: "Boston Accident Risk Rerouting",
      note: "Implementation evidence and live product proof are grouped together.",
      links: [
        ...githubProofAccessLinks.map((link, index) => ({ ...link, id: `combined-github-${index + 1}` })),
        ...websiteProofAccessLinks.map((link) => ({ ...link, id: "combined-website-1" })),
      ],
    },
    {
      id: "github-only-project",
      projectName: "Decision Tree Classification Model",
      note: "GitHub proof only. Website deployment is optional.",
      links: [{ ...githubProofAccessLinks[0]!, id: "github-only-code-lines-1" }],
    },
    {
      id: "website-only-project",
      projectName: "Route Risk Demo Deployment",
      note: "Public deployed proof only. No GitHub link is required here.",
      links: [{ ...websiteProofAccessLinks[0]!, id: "website-only-live-1" }],
    },
  ];
  const artifacts = [
    {
      icon: "↗",
      label: "Uploaded report",
      meta: "private upload · sales-dashboard.pdf",
      evidence: {
        skill: "Tableau",
        sourceType: "Dashboard / analytics report",
        evidenceAccessMethod: "upload_file" as const,
        evidenceTitle: "Sales dashboard report",
        uploadedFileName: "sales-dashboard.pdf",
        uploadedFileType: "application/pdf",
        uploadedFileSize: "2.4 MB",
        uploadedFileUrl: "",
        isRecruiterVisible: false,
        requiresApproval: false,
        visibilityNote: "Private uploads are only shown to authorized reviewers/recruiters based on sharing settings.",
        description: "Quarterly dashboard report with key business metrics.",
        verificationStatus: "Pending verification" as const,
        verificationSummary: "Uploaded evidence saved for recruiter review.",
      },
    },
    {
      icon: "⌥",
      label: "GitHub code file",
      meta: "maya/proof-app · app/main.py",
      evidence: {
        backendEvidenceId: "demo-github-evidence",
        skill: "Python",
        sourceType: "GitHub code file",
        evidenceAccessMethod: "public_link" as const,
        evidenceUrl: "https://github.com/maya/proof-app",
        filePath: "app/main.py",
        startLine: "20",
        endLine: "95",
        description: "Built FastAPI prediction endpoint.",
        verificationStatus: "Verified" as const,
        verificationSummary: "Python usage likely found ✅",
        accessLinks: githubProofAccessLinks,
      },
    },
    {
      icon: "▤",
      label: "Live website",
      meta: "student-app.example.com · public deployed proof",
      evidence: {
        backendEvidenceId: "demo-website-evidence",
        skill: "Web App",
        sourceType: "Deployed website",
        evidenceAccessMethod: "public_link" as const,
        evidenceUrl: "https://student-app.example.com",
        description: "Route risk checker with rerouting recommendation.",
        verificationStatus: "Verified" as const,
        verificationSummary: "Website flow matched the claimed route-risk feature.",
        accessLinks: websiteProofAccessLinks,
      },
    },
    {
      icon: "▣",
      label: "LinkedIn post",
      meta: "project showcase · public post",
      evidence: {
        skill: "Leadership",
        sourceType: "LinkedIn post",
        evidenceAccessMethod: "public_link" as const,
        linkedInPostUrl: "https://www.linkedin.com/posts/demo-project",
        relatedProjectUrl: "https://github.com/maya/proof-app",
        description: "LinkedIn post showcasing the hackathon build.",
        verificationStatus: "Pending verification" as const,
        verificationSummary: "LinkedIn post recorded for recruiter review.",
      },
    },
    {
      icon: "◇",
      label: "Shared certificate",
      meta: "Docker Foundations · shared with recruiters",
      evidence: {
        skill: "Docker",
        sourceType: "Certificate",
        evidenceAccessMethod: "upload_file" as const,
        evidenceTitle: "Docker Foundations Certificate",
        uploadedFileName: "docker-certificate.png",
        uploadedFileType: "image/png",
        uploadedFileSize: "1.1 MB",
        uploadedFileUrl: "https://files.veribridge.test/docker-certificate.png",
        isRecruiterVisible: true,
        requiresApproval: false,
        certificateIssuer: "Docker, Inc.",
        completionDate: "2025-04-12",
        description: "Completion certificate for Docker Foundations.",
        verificationStatus: "Pending verification" as const,
        verificationSummary: "Uploaded evidence saved for recruiter review.",
      },
    },
    {
      icon: "◐",
      label: "Approval required",
      meta: "architecture diagram · recruiter request access",
      evidence: {
        skill: "Architecture",
        sourceType: "Architecture diagram",
        evidenceAccessMethod: "upload_file" as const,
        evidenceTitle: "System architecture diagram",
        uploadedFileName: "architecture.png",
        uploadedFileType: "image/png",
        uploadedFileSize: "860 KB",
        uploadedFileUrl: "https://files.veribridge.test/architecture.png",
        isRecruiterVisible: true,
        requiresApproval: true,
        diagramUrl: "https://drive.google.com/file/d/demo",
        description: "Architecture diagram for the proof-of-skill build.",
        verificationStatus: "Pending verification" as const,
        verificationSummary: "Uploaded evidence saved for recruiter review.",
      },
    },
  ];

  const visibleProjectEvidenceBundles = realProofData.bundles.length > 0 ? realProofData.bundles : projectEvidenceBundles;
  const visibleArtifacts = realProofData.artifacts.length > 0 ? realProofData.artifacts : artifacts;
  const projectEvidenceHeaderNote = realProofData.loading
    ? "Loading real proof data from the backend…"
    : realProofData.bundles.length > 0
      ? "Real proof bundles loaded from backend submissions."
      : realProofData.error
        ? `Using demo proof examples because real backend proof could not be loaded yet: ${realProofData.error}`
        : "Demo proof examples are shown when no real backend evidence is available.";

  function getBundleTitle(bundle: RecruiterProjectEvidenceBundle | { projectName: string }) {
    return "projectTitle" in bundle ? bundle.projectTitle : bundle.projectName;
  }

  function getBundleLinks(bundle: RecruiterProjectEvidenceBundle | { links: EvidenceAccessLink[]; combinedAccessLinks?: EvidenceAccessLink[] }) {
    return "combinedAccessLinks" in bundle ? bundle.combinedAccessLinks ?? [] : bundle.links;
  }

  return (
    <div style={{ ...card, position: "sticky", top: 100, alignSelf: "start" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: "50%",
            background: maya.grad,
            display: "grid",
            placeItems: "center",
            fontWeight: 700,
            fontSize: 18,
            color: "#fff",
            flexShrink: 0,
          }}
        >
          {maya.initials}
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>{maya.name}</div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>{maya.school}</div>
          <span
            style={{
              display: "inline-block",
              marginTop: 4,
              fontSize: 10,
              fontWeight: 600,
              padding: "2px 7px",
              borderRadius: 4,
              background: "var(--emerald-soft)",
              color: "#065f46",
              fontFamily: "'JetBrains Mono',monospace",
            }}
          >
            .edu Verified
          </span>
        </div>
      </div>

      {/* PA grid 2x2 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
        {paStats.map(({ label, value }, index) => (
          <div
            key={`${label}-${index}`}
            style={{
              background: "var(--bg-2)",
              borderRadius: 8,
              padding: "10px 12px",
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 600, marginBottom: 4 }}>{label}</div>
            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 18, fontWeight: 700, color: "var(--ink)" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Verified skills */}
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>Verified Skills</div>
      <div style={{ marginBottom: 14 }}>
        {skills.map((s) => (
          <div
            key={s}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "7px 0",
              borderBottom: "1px solid var(--line)",
              fontSize: 12,
              color: "var(--ink-2)",
            }}
          >
            <span style={{ color: "var(--emerald)", fontWeight: 700 }}>✓</span>
            {s}
          </div>
        ))}
      </div>

      {/* Project evidence */}
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>Project Evidence</div>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10, lineHeight: 1.5 }}>{projectEvidenceHeaderNote}</div>
      <div style={{ display: "grid", gap: 10, marginBottom: 16 }}>
        {visibleProjectEvidenceBundles.map((bundle) => (
          <ProjectEvidenceActions
            key={bundle.id}
            dataTestId={`project-evidence-bundle-${bundle.id}`}
            projectName={getBundleTitle(bundle)}
            note={bundle.note ?? undefined}
            links={getBundleLinks(bundle)}
            compact
          />
        ))}
      </div>

      {/* Proof artifacts */}
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 8 }}>Proof Artifacts</div>
      <div style={{ marginBottom: 16 }}>
        {visibleArtifacts.map(({ icon, label, meta }, index) => {
          const active = activeEvidenceIndex === index;
          const evidence = visibleArtifacts[index].evidence as any;
          const visibilityLabel = getProofVisibilityLabel(
            Boolean(evidence.isRecruiterVisible),
            Boolean(evidence.requiresApproval),
            (evidence.evidenceAccessMethod as "public_link" | "upload_file") || "public_link",
            "recruiter"
          );
          return (
            <div
              key={`${label}-${index}`}
              style={{
                display: "grid",
                gap: 8,
                padding: "10px 10px",
                borderRadius: 10,
                marginBottom: 6,
                background: active ? "var(--indigo-soft)" : "var(--bg-2)",
                border: `1px solid ${active ? "#c7d2fe" : "transparent"}`,
                fontSize: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontSize: 14, width: 18, textAlign: "center" }}>{icon}</span>
                <span style={{ fontWeight: 700, color: "var(--ink-2)", minWidth: 104 }}>{label}</span>
                <span style={{ color: "var(--muted)" }}>{meta}</span>
                <div style={{ marginLeft: "auto" }}>
                  <Btn
                    variant="secondary"
                    onClick={() => setActiveEvidenceIndex(active ? -1 : index)}
                    data-testid={`evidence-toggle-${index}`}
                    style={{ padding: "6px 10px", fontSize: 12 }}
                  >
                    {active ? "Hide Evidence" : "Show Evidence"}
                  </Btn>
                </div>
              </div>
              {active && (
                <div
                  style={{
                    display: "grid",
                    gap: 10,
                    border: "1px solid var(--line)",
                    borderRadius: 12,
                    background: "#fff",
                    padding: 12,
                  }}
                >
                  <div style={{ display: "grid", gap: 4 }}>
                    <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Evidence preview</div>
                    <div style={{ fontWeight: 800, color: "var(--ink)" }}>{evidence.evidenceTitle ?? evidence.sourceType}</div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)" }}>Visibility: {visibilityLabel}</div>
                  </div>
                  {evidence.evidenceAccessMethod === "upload_file" ? (
                    !evidence.isRecruiterVisible ? (
                      <div
                        style={{
                          border: "1px dashed var(--line)",
                          borderRadius: 10,
                          background: "var(--bg-2)",
                          padding: 10,
                          color: "var(--muted)",
                          fontSize: 12,
                        }}
                      >
                        Evidence exists, but the student has not shared this private file.
                      </div>
                    ) : evidence.requiresApproval ? (
                      <div
                        style={{
                          border: "1px dashed var(--line)",
                          borderRadius: 10,
                          background: "var(--bg-2)",
                          padding: 10,
                          color: "var(--muted)",
                          fontSize: 12,
                          display: "grid",
                          gap: 8,
                        }}
                      >
                        <div>Request access to view this evidence.</div>
                        <Btn variant="secondary" onClick={() => onToast?.("Request access sent to student (demo).")}>Request access</Btn>
                      </div>
                    ) : (
                      <div style={{ display: "grid", gap: 4, color: "var(--ink-2)", fontSize: 12 }}>
                        <div><strong>Skill:</strong> {evidence.skill}</div>
                        <div><strong>Evidence source:</strong> {evidence.sourceType}</div>
                        {evidence.evidenceTitle && <div><strong>Evidence title:</strong> {evidence.evidenceTitle}</div>}
                        {evidence.uploadedFileName && <div><strong>Uploaded file:</strong> {evidence.uploadedFileName}</div>}
                        {evidence.uploadedFileType && <div><strong>File type:</strong> {evidence.uploadedFileType}</div>}
                        {evidence.uploadedFileSize && <div><strong>File size:</strong> {evidence.uploadedFileSize}</div>}
                        {evidence.description && <div><strong>Evidence description:</strong> {evidence.description}</div>}
                        {evidence.visibilityNote && <div><strong>Visibility note for recruiters:</strong> {evidence.visibilityNote}</div>}
                        <div><strong>Claim status:</strong> {evidence.verificationStatus}</div>
                        {evidence.verificationSummary && <div><strong>Verification summary:</strong> {evidence.verificationSummary}</div>}
                        {evidence.uploadedFileUrl && (
                          <div
                            style={{
                              border: "1px dashed var(--line)",
                              borderRadius: 10,
                              background: "var(--bg-2)",
                              padding: 10,
                              color: "var(--muted)",
                              fontSize: 12,
                            }}
                          >
                            Uploaded evidence preview placeholder for authorized reviewers.
                          </div>
                        )}
                        {evidence.uploadedFileUrl && (
                          <Btn
                            variant="secondary"
                            onClick={() => window.open(evidence.uploadedFileUrl, "_blank", "noopener,noreferrer")}
                            style={{ justifySelf: "start", padding: "6px 10px", fontSize: 12 }}
                          >
                            Open file
                          </Btn>
                        )}
                      </div>
                    )
                  ) : (
                    <div style={{ display: "grid", gap: 4, color: "var(--ink-2)", fontSize: 12 }}>
                      <div><strong>Skill:</strong> {evidence.skill}</div>
                      <div><strong>Evidence source:</strong> {evidence.sourceType}</div>
                      {evidence.evidenceUrl && <div><strong>Evidence URL:</strong> {evidence.evidenceUrl}</div>}
                      {evidence.linkedInPostUrl && <div><strong>LinkedIn post URL:</strong> {evidence.linkedInPostUrl}</div>}
                      {evidence.relatedProjectUrl && <div><strong>Related project/repository URL:</strong> {evidence.relatedProjectUrl}</div>}
                      {evidence.filePath && <div><strong>File path:</strong> {evidence.filePath}</div>}
                      {evidence.startLine && evidence.endLine && <div><strong>Lines:</strong> {evidence.startLine}–{evidence.endLine}</div>}
                      {evidence.uploadedFileName && <div><strong>Uploaded file:</strong> {evidence.uploadedFileName}</div>}
                      {evidence.uploadedFileType && <div><strong>File type:</strong> {evidence.uploadedFileType}</div>}
                      {evidence.uploadedFileSize && <div><strong>File size:</strong> {evidence.uploadedFileSize}</div>}
                      {evidence.description && <div><strong>Evidence description:</strong> {evidence.description}</div>}
                      {evidence.visibilityNote && <div><strong>Visibility note:</strong> {evidence.visibilityNote}</div>}
                      <div><strong>Claim status:</strong> {evidence.verificationStatus}</div>
                      {evidence.verificationSummary && <div><strong>Verification summary:</strong> {evidence.verificationSummary}</div>}
                      {(typeof evidence.backendEvidenceId === "string" || Array.isArray(evidence.accessLinks)) && (
                        <EvidenceAccessActions
                          evidenceId={typeof evidence.backendEvidenceId === "string" ? evidence.backendEvidenceId : undefined}
                          fallbackLinks={Array.isArray(evidence.accessLinks) ? evidence.accessLinks : []}
                          compact
                          className="recruiter-proof-access"
                        />
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 8 }}>
        <Btn variant="secondary" onClick={() => onToast?.("Candidate saved to your lists (demo).")}>Save</Btn>
        <Btn onClick={() => onToast?.("Invite sent — backend integration coming soon.")}>Send invite →</Btn>
      </div>
    </div>
  );
}

// ── Pipeline preview ───────────────────────────────────────────────────────

const pipelineStages = [
  {
    label: "Sourced",
    count: 18,
    color: "#e0e7ff",
    textColor: "var(--indigo)",
    cards: [
      { name: "Maya Reyes", meta: "WPI CS · score 94" },
      { name: "Jordan Kim", meta: "MIT EECS · score 91" },
    ],
  },
  {
    label: "Contacted",
    count: 10,
    color: "#fef3c7",
    textColor: "#92400e",
    cards: [
      { name: "Arjun Singh", meta: "CMU SCS · score 88" },
    ],
  },
  {
    label: "Interview",
    count: 9,
    color: "var(--emerald-soft)",
    textColor: "#065f46",
    cards: [
      { name: "Leila Pham", meta: "Stanford CS · score 86" },
    ],
  },
  {
    label: "Offer",
    count: 5,
    color: "var(--purple-soft)",
    textColor: "#5b21b6",
    cards: [],
  },
];

function PipelinePreview() {
  return (
    <div style={{ marginTop: 20 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 700,
          color: "var(--muted)",
          textTransform: "uppercase",
          letterSpacing: "0.14em",
          marginBottom: 10,
        }}
      >
        Pipeline
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        {pipelineStages.map((stage) => (
          <div key={stage.label}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 12, color: "var(--ink-2)" }}>{stage.label}</span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 10,
                  padding: "2px 6px",
                  borderRadius: 4,
                  background: stage.color,
                  color: stage.textColor,
                  fontWeight: 700,
                }}
              >
                {stage.count}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {stage.cards.map((c) => (
                <div
                  key={c.name}
                  style={{
                    padding: "8px 10px",
                    borderRadius: 8,
                    background: "var(--paper)",
                    border: "1px solid var(--line)",
                    fontSize: 12,
                  }}
                >
                  <div style={{ fontWeight: 600, color: "var(--ink)" }}>{c.name}</div>
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>{c.meta}</div>
                </div>
              ))}
              {stage.cards.length === 0 && (
                <div
                  style={{
                    padding: "8px 10px",
                    borderRadius: 8,
                    border: "1px dashed var(--line)",
                    fontSize: 11,
                    color: "var(--muted)",
                    textAlign: "center",
                  }}
                >
                  Empty
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main views ─────────────────────────────────────────────────────────────

export function RecruiterOverview() {
  const { show, msg } = useDemoToast();
  const [searchQuery, setSearchQuery] = useState("");
  const [searchState, setSearchState] = useState<RecruiterSearchState>({ status: "idle" });
  const [selectedResult, setSelectedResult] = useState<CandidateSearchResult | null>(null);
  const [detailState, setDetailState] = useState<DetailFetchState>({ status: "idle" });

  // Fetch real candidate detail whenever selection changes
  useEffect(() => {
    if (!selectedResult) {
      setDetailState({ status: "idle" });
      return;
    }
    let active = true;
    setDetailState({ status: "loading" });
    fetchRecruiterCandidateDetail(selectedResult.user_id)
      .then((detail) => {
        if (active) setDetailState({ status: "done", detail });
      })
      .catch((err) => {
        if (active)
          setDetailState({
            status: "error",
            error: err instanceof Error ? err.message : "Failed to load candidate detail.",
          });
      });
    return () => {
      active = false;
    };
  }, [selectedResult?.user_id]);

  async function handleSearch() {
    const q = searchQuery.trim();
    if (!q) return;
    setSearchState({ status: "loading", query: q });
    setSelectedResult(null);
    setDetailState({ status: "idle" });
    try {
      const response = await searchRecruiterCandidates(q);
      setSearchState({ status: "done", query: q, results: response.results });
      setSelectedResult(response.results[0] ?? null);
    } catch (err) {
      setSearchState({
        status: "error",
        query: q,
        error: err instanceof Error ? err.message : "Search failed. Please try again.",
      });
    }
  }

  function handleClearSearch() {
    setSearchQuery("");
    setSearchState({ status: "idle" });
    setSelectedResult(null);
    setDetailState({ status: "idle" });
  }

  const metrics = [
    { label: "Active candidates", value: "2,847", detail: "+312 this week", color: "var(--indigo)" },
    { label: "Profile views", value: "186", detail: "+24% vs last week", color: "var(--emerald)" },
    { label: "In pipeline", value: "42", detail: "14 in interview", color: "var(--purple)" },
    { label: "Trust score", value: "94", detail: "Top 5% verified recruiter", color: "var(--amber)" },
  ];

  const isSearchActive = searchState.status !== "idle";

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Recruiter console"
        title="Proof-backed candidate discovery"
        lede="Search verified early-career talent by evidence, readiness, role fit, and student-controlled work authorization visibility."
        action={
          <>
            <Btn variant="secondary" onClick={() => show("Export feature coming soon — backend integration required.")}>↓ Export</Btn>
            <Btn onClick={() => show("Job post creation coming soon.")}>+ New job post</Btn>
          </>
        }
      />

      {/* Metric cards */}
      <div className="vb-stagger" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16, marginBottom: 20 }}>
        {metrics.map((m) => (
          <div key={m.label} style={{ ...card }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 6 }}>{m.label}</div>
            <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 28, fontWeight: 700, color: m.color, lineHeight: 1 }}>{m.value}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>{m.detail}</div>
          </div>
        ))}
      </div>

      {/* Search bar */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: isSearchActive ? 8 : 12 }}>
          <input
            data-testid="recruiter-search-input"
            placeholder="Search by skill, school, role, or keyword..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
            style={{
              flex: 1,
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid var(--line)",
              fontSize: 14,
              background: "var(--bg-2)",
              color: "var(--ink)",
              outline: "none",
            }}
          />
          <Btn
            data-testid="recruiter-search-submit"
            onClick={handleSearch}
            disabled={searchState.status === "loading"}
          >
            {searchState.status === "loading" ? "Searching…" : "Search"}
          </Btn>
          {isSearchActive && (
            <Btn variant="secondary" onClick={handleClearSearch} data-testid="recruiter-search-clear">
              ✕ Clear
            </Btn>
          )}
        </div>
        {!isSearchActive && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600 }}>Try searching:</span>
            {["Machine Learning", "Docker", "FastAPI", "AWS", "NLP"].map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => { setSearchQuery(f); }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "4px 10px",
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  background: "var(--bg-2)",
                  color: "var(--ink-2)",
                  border: "1px solid var(--line)",
                  cursor: "pointer",
                }}
              >
                {f}
              </button>
            ))}
          </div>
        )}
        {isSearchActive && searchState.status === "done" && (
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {searchState.results.length > 0
              ? `${searchState.results.length} proof-backed candidate${searchState.results.length === 1 ? "" : "s"} found for "${searchState.query}"`
              : `No candidates found for "${searchState.query}"`}
          </div>
        )}
      </div>

      {/* 2-col grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 20 }}>

        {/* Left column — default or search results */}
        {searchState.status === "idle" && (
          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Demo · Proof-backed candidate cards</div>
                <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>Candidate search</div>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 11,
                  padding: "3px 9px",
                  borderRadius: 5,
                  background: "var(--indigo-soft)",
                  color: "var(--indigo)",
                  fontWeight: 700,
                }}
              >
                Demo
              </span>
            </div>
            <CandidateList />
            <PipelinePreview />
          </div>
        )}

        {searchState.status === "loading" && (
          <div style={card}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "24px 0", color: "var(--muted)", fontSize: 14 }}>
              <span style={{ animation: "recruiter-pulse 1.2s infinite", display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "var(--indigo)" }} />
              Searching for proof-backed candidates…
            </div>
          </div>
        )}

        {searchState.status === "done" && searchState.results.length > 0 && (
          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--emerald)", textTransform: "uppercase", letterSpacing: "0.12em" }}>Real search results · proof-backed</div>
                <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)" }}>"{searchState.query}"</div>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 11,
                  padding: "3px 9px",
                  borderRadius: 5,
                  background: "var(--emerald-soft)",
                  color: "#065f46",
                  fontWeight: 700,
                }}
              >
                {searchState.results.length} found
              </span>
            </div>
            <div data-testid="recruiter-search-results">
              {searchState.results.map((r) => (
                <SearchResultCandidateCard
                  key={r.user_id}
                  result={r}
                  selected={selectedResult?.user_id === r.user_id}
                  onClick={() => setSelectedResult(r)}
                />
              ))}
            </div>
          </div>
        )}

        {searchState.status === "done" && searchState.results.length === 0 && (
          <div style={card}>
            <div style={{ textAlign: "center", padding: "40px 20px" }}>
              <div style={{ fontSize: 32, marginBottom: 10 }}>🔍</div>
              <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 6 }} data-testid="recruiter-search-empty">
                No candidates found
              </div>
              <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 360, margin: "0 auto" }}>
                No proof-backed candidates matched "{searchState.query}". Try a broader skill name such as "Python", "Machine Learning", or "Cloud".
              </div>
            </div>
          </div>
        )}

        {searchState.status === "error" && (
          <div style={card}>
            <div style={{ textAlign: "center", padding: "40px 20px" }}>
              <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 6 }}>
                Search unavailable
              </div>
              <div style={{ fontSize: 13, color: "var(--muted)" }}>
                {searchState.error}
              </div>
            </div>
          </div>
        )}

        {/* Right column — detail panel */}
        {searchState.status === "idle" && <CandidatePreview onToast={show} />}
        {searchState.status === "done" && selectedResult && (
          <SearchResultDetailPanel result={selectedResult} detailState={detailState} />
        )}
        {searchState.status === "done" && !selectedResult && (
          <div style={{ ...card, display: "grid", placeItems: "center", minHeight: 200 }}>
            <div style={{ fontSize: 13, color: "var(--muted)", textAlign: "center" }}>
              Select a candidate to see their proof summary.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function RecruiterSearch() {
  const { show, msg } = useDemoToast();

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Recruiter console · Pipeline"
        title="Pipeline"
        lede="Track candidates from sourcing through offer. Drag to advance stages."
        action={<Btn onClick={() => show("Add candidate — backend integration coming soon.")}>+ Add candidate</Btn>}
      />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 16 }}>
        {pipelineStages.map((stage) => (
          <div key={stage.label} style={card}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 14,
              }}
            >
              <span style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)" }}>{stage.label}</span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 12,
                  padding: "3px 8px",
                  borderRadius: 5,
                  background: stage.color,
                  color: stage.textColor,
                  fontWeight: 700,
                }}
              >
                {stage.count}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {candidates.slice(0, stage.count > 1 ? 3 : 1).map((c) => (
                <div
                  key={`${stage.label}-${c.name}`}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 8,
                    background: "var(--bg-2)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13, color: "var(--ink)", marginBottom: 2 }}>{c.name}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>{c.school} · score {c.score}</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RecruiterCandidates() {
  const { show, msg } = useDemoToast();

  const lists = [
    { name: "Backend Engineers · Class of 2026", count: 14, updated: "2d ago" },
    { name: "F-1 Visa · ML/Data", count: 8, updated: "1d ago" },
    { name: "WPI · Distributed Systems", count: 6, updated: "5d ago" },
  ];

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Recruiter console · Saved Lists"
        title="Saved Lists"
        lede="Organize shortlisted candidates into reusable talent pools."
        action={<Btn onClick={() => show("New list creation — backend integration coming soon.")}>+ New list</Btn>}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 20 }}>
        <div>
          <div style={{ ...card, marginBottom: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Your lists</div>
            {lists.map((list, i) => (
              <div
                key={list.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "12px 0",
                  borderBottom: i < lists.length - 1 ? "1px solid var(--line)" : "none",
                  cursor: "pointer",
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)", marginBottom: 2 }}>{list.name}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>{list.count} candidates · updated {list.updated}</div>
                </div>
                <span style={{ color: "var(--muted)", fontSize: 16 }}>→</span>
              </div>
            ))}
          </div>
          <div style={card}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Candidates in: Backend Engineers · Class of 2026</div>
            <CandidateList />
          </div>
        </div>
        <CandidatePreview onToast={show} />
      </div>
    </div>
  );
}

export function RecruiterInvites() {
  const { show, msg } = useDemoToast();

  const threads = [
    { name: "Maya Reyes", school: "WPI CS '26", preview: "Thanks for reaching out! I'm interested...", time: "2h ago", unread: true },
    { name: "Jordan Kim", school: "MIT EECS '26", preview: "Would love to hear more about the role.", time: "1d ago", unread: false },
    { name: "Arjun Singh", school: "CMU SCS '26", preview: "I have a few questions about the team...", time: "2d ago", unread: false },
    { name: "Leila Pham", school: "Stanford CS '26", preview: "Following up on the interview schedule.", time: "3d ago", unread: false },
  ];

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Recruiter console · Messages"
        title="Messages"
        lede="Candidate conversations and interview scheduling."
        action={<Btn onClick={() => show("New message — backend integration coming soon.")}>+ New message</Btn>}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 20 }}>
        <div style={card}>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Conversations</div>
          {threads.map((t, i) => (
            <div
              key={t.name}
              style={{
                display: "flex",
                gap: 12,
                padding: "12px 0",
                borderBottom: i < threads.length - 1 ? "1px solid var(--line)" : "none",
                cursor: "pointer",
              }}
            >
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  background: candidates[i % candidates.length].grad,
                  display: "grid",
                  placeItems: "center",
                  color: "#fff",
                  fontWeight: 600,
                  fontSize: 12,
                  flexShrink: 0,
                }}
              >
                {candidates[i % candidates.length].initials}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                  <span style={{ fontWeight: t.unread ? 700 : 600, fontSize: 13, color: "var(--ink)" }}>{t.name}</span>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>{t.time}</span>
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 1 }}>{t.school}</div>
                <div
                  style={{
                    fontSize: 12,
                    color: t.unread ? "var(--ink-2)" : "var(--muted)",
                    fontWeight: t.unread ? 500 : 400,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {t.preview}
                </div>
              </div>
              {t.unread && (
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: "var(--indigo)",
                    alignSelf: "center",
                    flexShrink: 0,
                  }}
                />
              )}
            </div>
          ))}
        </div>
        <div style={card}>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 4 }}>Maya Reyes</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 16 }}>WPI CS '26 · score 94</div>
          <div
            style={{
              height: 280,
              background: "var(--bg-2)",
              borderRadius: 10,
              padding: 16,
              marginBottom: 14,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <div
              style={{
                alignSelf: "flex-start",
                background: "var(--paper)",
                border: "1px solid var(--line)",
                borderRadius: "12px 12px 12px 2px",
                padding: "8px 12px",
                fontSize: 13,
                maxWidth: "80%",
              }}
            >
              Hi Maya, I came across your VeriBridge profile — your Docker and distributed systems work is exactly what we need at Stripe. Are you open to a quick chat?
            </div>
            <div
              style={{
                alignSelf: "flex-end",
                background: "var(--indigo)",
                borderRadius: "12px 12px 2px 12px",
                padding: "8px 12px",
                fontSize: 13,
                color: "#fff",
                maxWidth: "80%",
              }}
            >
              Thanks for reaching out! I&apos;m very interested — what does the timeline look like?
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              placeholder="Reply..."
              style={{
                flex: 1,
                padding: "9px 12px",
                borderRadius: 8,
                border: "1px solid var(--line)",
                fontSize: 13,
                background: "var(--bg-2)",
                color: "var(--ink)",
                outline: "none",
              }}
              readOnly
            />
            <Btn onClick={() => show("Message send — backend integration coming soon.")}>Send</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

export function RecruiterCompany() {
  const { show, msg } = useDemoToast();

  const jobs = [
    { title: "Backend Engineer, Intern", dept: "Platform", location: "NYC · Remote", visa: "H-1B friendly", applicants: 24, status: "Active" },
    { title: "Full-Stack Engineer, New Grad", dept: "Payments", location: "SF · Hybrid", visa: "H-1B friendly", applicants: 18, status: "Active" },
    { title: "Data Engineer, Intern", dept: "Data Science", location: "NYC", visa: "All visa types", applicants: 12, status: "Draft" },
  ];

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Recruiter console · Job Posts"
        title="Job Posts"
        lede="Manage your open roles and company profile visible to students."
        action={<Btn onClick={() => show("Job post creation coming soon.")}>+ New job post</Btn>}
      />
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 20 }}>
        <div>
          <div style={{ ...card, marginBottom: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Active job posts</div>
            {jobs.map((job, i) => (
              <div
                key={job.title}
                style={{
                  padding: "14px 0",
                  borderBottom: i < jobs.length - 1 ? "1px solid var(--line)" : "none",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "var(--ink)", marginBottom: 2 }}>{job.title}</div>
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>
                      {job.dept} · {job.location}
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <span
                        style={{
                          fontSize: 10,
                          padding: "2px 7px",
                          borderRadius: 4,
                          background: "var(--emerald-soft)",
                          color: "#065f46",
                          fontWeight: 600,
                        }}
                      >
                        {job.visa}
                      </span>
                      <span
                        style={{
                          fontSize: 10,
                          padding: "2px 7px",
                          borderRadius: 4,
                          background: job.status === "Active" ? "var(--indigo-soft)" : "var(--bg-2)",
                          color: job.status === "Active" ? "var(--indigo)" : "var(--muted)",
                          fontWeight: 600,
                        }}
                      >
                        {job.status}
                      </span>
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 20, fontWeight: 700, color: "var(--indigo)" }}>{job.applicants}</div>
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>applicants</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div style={{ ...card, marginBottom: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>Company profile</div>
            {[
              ["Company", "Stripe"],
              ["Industry", "Fintech · Payments"],
              ["Early talent hiring", "Backend, Full-stack, Platform"],
              ["Locations", "NYC, SF, Remote"],
              ["Visa friendliness", "89 / 100"],
              ["H-1B sponsorship", "Strong signal"],
            ].map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--line)", fontSize: 13 }}>
                <span style={{ color: "var(--muted)", fontWeight: 500 }}>{k}</span>
                <span style={{ fontWeight: 600, color: "var(--ink)" }}>{v}</span>
              </div>
            ))}
          </div>
          <div style={card}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 8 }}>Recruiter trust score</div>
            <div
              style={{
                height: 8,
                borderRadius: 4,
                background: "var(--bg-2)",
                marginBottom: 6,
                overflow: "hidden",
              }}
            >
              <div style={{ width: "94%", height: "100%", borderRadius: 4, background: "var(--indigo)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)" }}>
              <span>94 / 100</span>
              <span>Top 5%</span>
            </div>
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 10, lineHeight: 1.6 }}>
              Verified company identity, response rate, and job-post clarity improve student opt-in rates for sensitive visibility fields.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export function RecruiterSettings() {
  const { show, msg } = useDemoToast();

  const sections: Array<{ title: string; items: Array<{ label: string; sub?: string; on: boolean }> }> = [
    {
      title: "Search defaults",
      items: [
        { label: "Require proof-backed skills", sub: "Only show candidates with verified evidence", on: true },
        { label: "Hide non-consenting visa details", sub: "Student-controlled visibility is always respected", on: true },
        { label: "Prioritize .edu verified profiles", sub: "Elevate institutionally-verified students", on: true },
      ],
    },
    {
      title: "Invite preferences",
      items: [
        { label: "Use student-first language", sub: "Frame invites around the student's goals", on: true },
        { label: "Include role salary range", sub: "Salary transparency improves response rates", on: true },
        { label: "Show visa compatibility only when opted in", sub: "Never expose visa details without student consent", on: true },
      ],
    },
    {
      title: "Notifications",
      items: [
        { label: "New high-match candidates", sub: "Alert when score ≥ 85 candidates appear", on: true },
        { label: "Invite replies", sub: "Real-time when a student responds", on: true },
        { label: "Pipeline follow-ups", sub: "Weekly digest of pending actions", on: false },
      ],
    },
  ];

  return (
    <div>
      <DemoToast msg={msg} />
      <PageHeader
        crumb="Recruiter console · Team & Billing"
        title="Team & Billing"
        lede="Manage your team seats, subscription, and recruiter preferences."
      />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {sections.map((section) => (
          <div key={section.title} style={card}>
            <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 14 }}>{section.title}</div>
            {section.items.map((item) => (
              <SwitchRow
                key={item.label}
                label={item.label}
                sub={item.sub}
                defaultOn={item.on}
                onToast={show}
              />
            ))}
          </div>
        ))}
        <div style={card}>
          <div style={{ fontWeight: 700, fontSize: 16, color: "var(--ink)", marginBottom: 8 }}>Privacy reminder</div>
          <p style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.7 }}>
            Recruiters should not see private visa/work authorization details unless the student opted in. Work authorization visibility is student-controlled.
          </p>
          <div
            style={{
              marginTop: 12,
              padding: "10px 12px",
              borderRadius: 8,
              background: "var(--indigo-soft)",
              border: "1px solid #c7d2fe",
              fontSize: 12,
              fontWeight: 600,
              color: "var(--indigo)",
            }}
          >
            ✓ Compliant with recruiter policy
          </div>
        </div>
      </div>
    </div>
  );
}
