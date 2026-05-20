"use client";

import { ExternalLink } from "lucide-react";
import type { EvidenceAccessLink } from "@/lib/api";

type ProjectEvidenceActionsProps = {
  projectName: string;
  links: EvidenceAccessLink[];
  compact?: boolean;
  className?: string;
  dataTestId?: string;
  note?: string;
};

function isAvailable(link: EvidenceAccessLink): boolean {
  return link.availability_status === "available" && Boolean(link.url);
}

function formatLineRange(link: EvidenceAccessLink): string | null {
  if (typeof link.line_start !== "number") return null;
  if (typeof link.line_end !== "number" || link.line_start === link.line_end) {
    return `Line ${link.line_start}`;
  }
  return `Lines ${link.line_start}–${link.line_end}`;
}

function buildButtonLabel(link: EvidenceAccessLink, githubCount: number): string {
  if (link.access_type === "live_website") {
    return link.label || "Open Live Website";
  }
  const range = formatLineRange(link);
  if (range && githubCount > 1) {
    return `View Code ${range}`;
  }
  return link.label || "View Exact Code Lines";
}

export function ProjectEvidenceActions({
  projectName,
  links,
  compact = false,
  className,
  dataTestId,
  note,
}: ProjectEvidenceActionsProps) {
  const availableLinks = links.filter(isAvailable);
  if (!availableLinks.length) {
    return null;
  }

  const githubCount = availableLinks.filter((link) => link.access_type === "github_exact_lines").length;

  return (
    <section
      className={className}
      data-testid={dataTestId}
      style={{
        border: "1px solid var(--line)",
        borderRadius: 12,
        background: "var(--bg-2)",
        padding: compact ? 12 : 14,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "grid", gap: 2 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.1em" }}>
          Project Evidence
        </div>
        <div style={{ fontWeight: 700, fontSize: 14, color: "var(--ink)" }}>{projectName}</div>
        {note && <div style={{ fontSize: 12, color: "var(--muted)" }}>{note}</div>}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "flex-start",
        }}
      >
        {availableLinks.map((link) => {
          const label = buildButtonLabel(link, githubCount);
          const range = formatLineRange(link);
          return (
            <div key={link.id} style={{ display: "grid", gap: 4 }}>
              <a
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                data-testid={`project-evidence-link-${link.id}`}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  width: "fit-content",
                  padding: "8px 12px",
                  borderRadius: 8,
                  border: "1px solid var(--line)",
                  background: "#fff",
                  color: "var(--ink)",
                  fontSize: 13,
                  fontWeight: 600,
                  textDecoration: "none",
                  lineHeight: 1.2,
                  whiteSpace: "nowrap",
                }}
              >
                <span>{label}</span>
                <ExternalLink size={14} />
              </a>
              {!compact && (
                <div style={{ fontSize: 11, color: "var(--muted)" }}>
                  {link.source_type === "github" && link.file_path
                    ? `${link.file_path}${range ? ` · ${range.toLowerCase()}` : ""}`
                    : "Public deployed proof"}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
