"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getLatestEvidenceAccessLinks,
  type EvidenceAccessLink,
} from "@/lib/api";

type EvidenceAccessActionsProps = {
  evidenceId?: string;
  links?: EvidenceAccessLink[];
  fallbackLinks?: EvidenceAccessLink[];
  compact?: boolean;
  loading?: boolean;
  className?: string;
};

function formatLineRange(link: EvidenceAccessLink): string | null {
  if (typeof link.line_start !== "number") return null;
  if (typeof link.line_end !== "number" || link.line_end === link.line_start) {
    return `line ${link.line_start}`;
  }
  return `lines ${link.line_start}–${link.line_end}`;
}

function buildLabel(link: EvidenceAccessLink, totalGithubLinks: number): string {
  if (link.access_type === "live_website") {
    return link.label || "Open Live Website";
  }
  const range = formatLineRange(link);
  if (totalGithubLinks > 1 && range) {
    const lineText = range.startsWith("lines ") ? `Lines ${range.slice(6)}` : `Line ${range.slice(5)}`;
    return `View Code ${lineText}`;
  }
  return link.label || "View Exact Code Lines";
}

function isAvailable(link: EvidenceAccessLink): boolean {
  return link.availability_status === "available" && Boolean(link.url);
}

export function EvidenceAccessActions({
  evidenceId,
  links,
  fallbackLinks = [],
  compact = false,
  loading = false,
  className,
}: EvidenceAccessActionsProps) {
  const [remoteLinks, setRemoteLinks] = useState<EvidenceAccessLink[] | null>(null);
  const [remoteLoading, setRemoteLoading] = useState(Boolean(evidenceId) && !links);

  useEffect(() => {
    let active = true;

    if (!evidenceId || links) {
      return () => {
        active = false;
      };
    }

    setRemoteLoading(true);
    getLatestEvidenceAccessLinks(evidenceId)
      .then((results) => {
        if (!active) return;
        setRemoteLinks(results);
      })
      .catch(() => {
        if (!active) return;
        setRemoteLinks(null);
      })
      .finally(() => {
        if (!active) return;
        setRemoteLoading(false);
      });

    return () => {
      active = false;
    };
  }, [evidenceId, links]);

  const resolvedLinks = links ?? remoteLinks ?? fallbackLinks;
  const availableLinks = useMemo(() => resolvedLinks.filter(isAvailable), [resolvedLinks]);
  const unavailableLinks = useMemo(() => resolvedLinks.filter((link) => !isAvailable(link)), [resolvedLinks]);
  const githubLinkCount = useMemo(
    () => availableLinks.filter((link) => link.access_type === "github_exact_lines").length,
    [availableLinks]
  );

  if ((loading || remoteLoading) && !availableLinks.length) {
    return (
      <div
        className={className}
        style={{
          fontSize: 12,
          color: "var(--muted)",
          padding: "8px 0 0",
        }}
      >
        Loading direct evidence access…
      </div>
    );
  }

  if (!availableLinks.length) {
    const note = unavailableLinks[0]?.notes ?? "Direct evidence access unavailable.";
    return (
      <div
        className={className}
        style={{
          fontSize: 12,
          color: "var(--muted)",
          padding: "8px 0 0",
        }}
      >
        {note}
      </div>
    );
  }

  return (
    <div className={className} style={{ display: "grid", gap: compact ? 8 : 10 }}>
      {availableLinks.map((link) => {
        const lineRange = formatLineRange(link);
        const buttonLabel = buildLabel(link, githubLinkCount);
        return (
          <div key={link.id} style={{ display: "grid", gap: 4 }}>
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              data-testid={`evidence-access-link-${link.access_type}-${link.id}`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                width: "fit-content",
                padding: "8px 12px",
                borderRadius: 8,
                border: "1px solid var(--line)",
                background: "var(--bg-2)",
                color: "var(--ink)",
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
                lineHeight: 1.2,
              }}
            >
              <span>{buttonLabel}</span>
              <ExternalLink size={14} />
            </a>
            {!compact && (
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {link.source_type === "github" && link.file_path
                  ? `${link.file_path}${lineRange ? ` · ${lineRange}` : ""}`
                  : "Public deployed proof"}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
