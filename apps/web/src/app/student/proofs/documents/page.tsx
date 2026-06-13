"use client"

import Link from "next/link"
import { DocumentProofPanel } from "../../../../../components/passport/DocumentProofPanel"
import { PageHeader, TOKEN } from "../../../../../components/passport/shared"

export default function DocumentProofStudioPage() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <Link
        href="/student/vbr"
        style={{
          fontSize: 13,
          color: TOKEN.indigo,
          textDecoration: "none",
          display: "inline-block",
          marginBottom: 16,
        }}
      >
        ← Back to Proof Studio
      </Link>

      <PageHeader
        eyebrow="Document Proof"
        title="Document Proof / Supporting Evidence"
        description="Add project reports, certificates, transcripts, or written explanations as supporting evidence for your skills. Documents are never treated as fully verified proof on their own."
      />

      <DocumentProofPanel />
    </div>
  )
}
