"use client"

import { isSafePublicUrl, type DocumentProofInspectionCard as DocumentProofInspectionCardData } from "@/lib/vbr-api"
import { Badge, Mono, TOKEN } from "./shared"

/**
 * Skill-specific, recruiter-facing inspection view of one Document Proof.
 *
 * The Document-Proof analogue of the GitHub / Website "inspection" card: it shows
 * a recruiter WHAT the document says (a bounded safe excerpt), WHERE it says it
 * (page / section / citation / figure-table locator), and WHY that supports the
 * SELECTED skill — never a whole-document dump. It renders ONLY the already-safe
 * fields on the DTO: it never receives (and so can never render) raw document
 * text, OCR/provider JSON, storage/bucket paths, signed URLs, or internal ids.
 *
 * Download/Open is shown ONLY when the backend marked the document downloadable
 * AND supplied a safe URL (revalidated here with {@link isSafePublicUrl}); every
 * other case shows the safe disabled/private access note instead.
 */
export function DocumentProofInspectionCard({ card }: { card: DocumentProofInspectionCardData }) {
  const hasLocator =
    card.page_number != null || !!card.section_label || !!card.citation_label
  const visuals = [card.figure_reference, card.table_reference, card.diagram_reference].filter(
    Boolean,
  ) as string[]

  const downloadUrl = card.document_download_url && isSafePublicUrl(card.document_download_url) ? card.document_download_url : null
  const openUrl = card.document_open_url && isSafePublicUrl(card.document_open_url) ? card.document_open_url : null
  const canDownload = !!card.can_download_document && (!!downloadUrl || !!openUrl)

  return (
    <div
      data-testid="document-inspection-card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "12px 14px",
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        background: "#fff",
      }}
    >
      {/* Header + evidence-role badge */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge tone="sky">Document Proof inspection</Badge>
        <span data-testid="document-inspection-role">
          <Badge tone="amber">{card.evidence_role || "Supporting evidence"}</Badge>
        </span>
        {card.matched_skill && (
          <span data-testid="document-inspection-skill" style={{ fontSize: 11, color: TOKEN.muted }}>
            {card.matched_skill}
          </span>
        )}
      </div>

      {card.title && (
        <div data-testid="document-inspection-title" style={{ fontSize: 13, fontWeight: 700, color: TOKEN.ink }}>
          {card.title}
        </div>
      )}
      {card.project_title && (
        <div style={{ fontSize: 11, color: TOKEN.muted }}>Project: {card.project_title}</div>
      )}

      {/* What this document supports */}
      {card.why_supported && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: TOKEN.inkSoft, marginBottom: 2 }}>
            What this document supports
          </div>
          <p data-testid="document-inspection-why" style={{ fontSize: 12, color: TOKEN.inkSoft, margin: 0, lineHeight: 1.5 }}>
            {card.why_supported}
          </p>
        </div>
      )}

      {/* Evidence locator: page / section / citation */}
      {hasLocator ? (
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: TOKEN.inkSoft, marginBottom: 2 }}>
            Evidence locator
          </div>
          <Mono data-testid="document-inspection-locator" style={{ fontSize: 12, color: TOKEN.inkSoft }}>
            {[
              card.page_number != null ? `Page ${card.page_number}` : null,
              card.section_label ? `§ ${card.section_label}` : null,
              card.citation_label && card.citation_label !== card.section_label ? card.citation_label : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </Mono>
        </div>
      ) : (
        <p data-testid="document-inspection-no-locator" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
          No skill-specific page/section/citation locator was extracted.
        </p>
      )}

      {/* Skill-related excerpt — bounded snippet only. Stripped on public views. */}
      {card.safe_snippet && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: TOKEN.inkSoft, marginBottom: 2 }}>
            Skill-related excerpt
          </div>
          <p data-testid="document-inspection-snippet" style={{ fontSize: 12, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
            “{card.safe_snippet}”
          </p>
        </div>
      )}

      {/* Related figure/table/graph — safe reference labels only. */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: TOKEN.inkSoft, marginBottom: 2 }}>
          Related figure/table
        </div>
        {visuals.length > 0 ? (
          <div data-testid="document-inspection-visuals" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {visuals.map((ref) => (
              <Badge key={ref} tone="slate">
                {ref}
              </Badge>
            ))}
          </div>
        ) : (
          <p data-testid="document-inspection-no-visual" style={{ fontSize: 11, color: TOKEN.muted, margin: 0 }}>
            {card.visual_or_table_summary || "No skill-specific figure/table evidence was extracted from this document."}
          </p>
        )}
      </div>

      {/* Corroborates */}
      {card.corroborates && (
        <div data-testid="document-inspection-corroborates" style={{ fontSize: 11, color: TOKEN.muted }}>
          <strong style={{ color: TOKEN.inkSoft }}>Corroborates: </strong>
          {card.corroborates}
        </div>
      )}

      {/* Limitation / corroboration language — always present. */}
      {card.limitation && (
        <div data-testid="document-inspection-limitation" style={{ fontSize: 11, color: TOKEN.muted, lineHeight: 1.5 }}>
          <strong style={{ color: TOKEN.inkSoft }}>Limitation: </strong>
          {card.limitation}
        </div>
      )}

      {/* Document access: download/open when safe, otherwise a helper note. */}
      <div style={{ borderTop: `1px solid ${TOKEN.line}`, paddingTop: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: TOKEN.inkSoft, marginBottom: 4 }}>
          Document access
        </div>
        {canDownload ? (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {downloadUrl && (
              <a
                href={downloadUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="document-inspection-download"
                style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "underline" }}
              >
                Download document
              </a>
            )}
            {openUrl && (
              <a
                href={openUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-testid="document-inspection-open"
                style={{ fontSize: 12, color: TOKEN.indigo, textDecoration: "underline" }}
              >
                Open original document
              </a>
            )}
          </div>
        ) : (
          <div
            data-testid="document-inspection-access-note"
            style={{ fontSize: 11, color: TOKEN.muted }}
          >
            🔒 {card.access_note || "Original document download is not available from this view yet."}
          </div>
        )}
      </div>
    </div>
  )
}
