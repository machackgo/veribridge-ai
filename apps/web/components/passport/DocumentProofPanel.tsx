"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import {
  listDocumentProofs,
  submitDocumentProof,
  uploadDocumentProof,
  syncDocumentProofToSkillGraph,
  type DocumentProofResponse,
  type DocumentProofSourceType,
} from "@/lib/passport-api"
import { readReturnToFromLocation } from "./safe-return"
import { ProofProjectAttachPanel } from "./ProofProjectAttachPanel"
import {
  Badge,
  Btn,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  StatusBadge,
  TOKEN,
} from "./shared"

type SyncStatus = "syncing" | "saved" | "error"

function evidenceItems(proof: DocumentProofResponse): Array<Record<string, unknown>> {
  return (proof.evidence_objects || []).slice(0, 5)
}

function DocumentProofCard({
  proof,
  syncStatus,
  onSync,
  onAttached,
}: {
  proof: DocumentProofResponse
  syncStatus?: SyncStatus
  onSync: (id: string) => void
  onAttached: () => void
}) {
  const items = evidenceItems(proof)
  const skills = Array.from(
    new Set(items.map((e) => String(e.skill_name || "")).filter(Boolean)),
  )

  return (
    <Card style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div style={{ fontSize: 22, flexShrink: 0 }}>📄</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>
              {proof.title || proof.filename || "Untitled document"}
            </span>
            <StatusBadge status={proof.status} />
            <Badge tone={proof.source_type === "certificate_transcript" ? "purple" : "slate"}>
              {proof.source_type === "certificate_transcript" ? "Certificate / Transcript" : "Document"}
            </Badge>
            {/* Canonical relationship state — the SAME rows the Passport and
                reports read; a display title can never fake attachment. */}
            <span data-testid="document-relationship-state" data-state={proof.project_relationship_state ?? "vault_only"}>
              {proof.project_relationship_state === "directly_linked" && proof.project_title ? (
                <Badge tone="emerald">Attached to {proof.project_title}</Badge>
              ) : (
                <Badge tone="amber">Needs project attachment — not counted in project reports</Badge>
              )}
            </span>
          </div>

          {proof.filename && (
            <Mono style={{ fontSize: 11, color: TOKEN.muted }}>{proof.filename}</Mono>
          )}

          {proof.claimed_skills.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Claimed Skills
              </Mono>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
                {proof.claimed_skills.map((s) => (
                  <Badge key={s} tone="indigo">{s}</Badge>
                ))}
              </div>
            </div>
          )}

          {skills.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.emerald, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Detected Skills
              </Mono>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 4 }}>
                {skills.map((s) => (
                  <Badge key={s} tone="emerald">{s}</Badge>
                ))}
              </div>
            </div>
          )}

          {items.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.12em" }}>
                Evidence Snippets
              </Mono>
              <ul style={{ margin: "4px 0 0", padding: "0 0 0 14px" }}>
                {items.map((e, i) => (
                  <li key={i} style={{ fontSize: 12, color: TOKEN.inkSoft, marginBottom: 2 }}>
                    {String(e.snippet || "").slice(0, 160)}
                    {String(e.snippet || "").length > 160 ? "…" : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {proof.status === "needs_review" && (
            <p style={{ fontSize: 12, color: TOKEN.muted, marginTop: 8 }}>
              No clear skill evidence was found in this submission. Add more detail and resubmit.
            </p>
          )}
          {(proof.status === "no_text_found" || proof.status === "extraction_failed" || proof.status === "unsupported_file") && (
            <p style={{ fontSize: 12, color: TOKEN.rose, marginTop: 8 }}>
              We couldn&apos;t extract text from this file.
            </p>
          )}

          {/* Save skill suggestions (pipeline sync). Honest wording: this NEVER
              attaches the document to a project or makes it report-countable —
              only the explicit project attachment (canonical relationship) does. */}
          {proof.status === "analyzed" && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              {(!syncStatus || syncStatus === "error") && (
                <Btn size="sm" variant="primary" onClick={() => onSync(proof.id)}>
                  Save skill suggestions
                </Btn>
              )}
              {syncStatus === "syncing" && (
                <Mono style={{ fontSize: 11, color: TOKEN.muted }}>Saving skill suggestions…</Mono>
              )}
              {syncStatus === "saved" && (
                <Mono style={{ fontSize: 11, color: TOKEN.emerald }}>
                  ✓ Skill suggestions saved — attach this document to a project for it to count in reports.
                </Mono>
              )}
              {syncStatus === "error" && (
                <Mono style={{ fontSize: 11, color: TOKEN.rose }}>Couldn&apos;t save skill suggestions.</Mono>
              )}
            </div>
          )}

          {/* Explicit project attachment — the shared canonical finalization
              flow (existing project / create new / keep vault-only). Shown for
              analyzed documents so a Document-only project can appear in the
              Work Passport without any Website Proof. */}
          {proof.status === "analyzed" && (
            <ProofProjectAttachPanel
              proofType="document"
              proofId={proof.id}
              relationshipState={proof.project_relationship_state}
              attachedProjectTitle={proof.project_title}
              defaultProjectTitle={proof.title || ""}
              onAttached={onAttached}
            />
          )}

          {proof.created_at && (
            <Mono style={{ fontSize: 10, color: TOKEN.muted, marginTop: 8, display: "block" }}>
              Submitted: {new Date(proof.created_at).toLocaleDateString()}
            </Mono>
          )}
        </div>
      </div>
    </Card>
  )
}

type Mode = "paste" | "upload"

export function DocumentProofPanel() {
  const router = useRouter()
  // A safe internal path (e.g. from Project Defense) to return to after a
  // successful submission. Validated to /student/ paths only — never external.
  const [returnTo] = useState<string | null>(() => readReturnToFromLocation())

  const [proofs, setProofs] = useState<DocumentProofResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncState, setSyncState] = useState<Record<string, SyncStatus>>({})

  const [showForm, setShowForm] = useState(false)
  const [mode, setMode] = useState<Mode>("paste")
  const [sourceType, setSourceType] = useState<DocumentProofSourceType>("document")
  const [title, setTitle] = useState("")
  const [rawText, setRawText] = useState("")
  const [claimedSkills, setClaimedSkills] = useState("")
  const [description, setDescription] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    listDocumentProofs()
      .then(setProofs)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const runSync = async (id: string) => {
    setSyncState((prev) => ({ ...prev, [id]: "syncing" }))
    try {
      const result = await syncDocumentProofToSkillGraph(id)
      const didSave =
        result.ok &&
        (result.already_synced || result.artifacts_created > 0) &&
        result.errors.length === 0
      setSyncState((prev) => ({ ...prev, [id]: didSave ? "saved" : "error" }))
    } catch {
      setSyncState((prev) => ({ ...prev, [id]: "error" }))
    }
  }

  const resetForm = () => {
    setTitle("")
    setRawText("")
    setClaimedSkills("")
    setDescription("")
    setFile(null)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const claimedSkillsList = () =>
    claimedSkills.split(",").map((s) => s.trim()).filter(Boolean)

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    try {
      let proof: DocumentProofResponse
      if (mode === "upload") {
        if (!file) {
          setSubmitError("Choose a file to upload (PDF, DOCX, TXT, or MD).")
          return
        }
        proof = await uploadDocumentProof(file, {
          title: title.trim() || undefined,
          claimed_skills: claimedSkillsList(),
          description: description.trim() || undefined,
          source_type: sourceType,
        })
      } else {
        if (!rawText.trim()) {
          setSubmitError("Paste some text describing your project or report.")
          return
        }
        proof = await submitDocumentProof({
          source_type: sourceType,
          raw_text: rawText.trim(),
          title: title.trim() || null,
          claimed_skills: claimedSkillsList(),
          description: description.trim() || null,
        })
      }
      setProofs((prev) => [proof, ...prev])
      resetForm()
      setShowForm(false)
      // If the student came from another proof-studio flow (e.g. Project
      // Defense) via a safe internal returnTo, send them back there.
      if (returnTo) router.push(returnTo)
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Submission failed")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Document Proof Submissions</h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Add project reports, certificates, or transcripts as supporting evidence for your skills.
          </p>
        </div>
        <Btn variant="primary" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ Add Document"}
        </Btn>
      </div>

      {showForm && (
        <Card style={{ border: `1px solid ${TOKEN.indigo}40`, background: TOKEN.indigoSoft }}>
          <CardHeader title="Submit Document or Certificate" eyebrow="New supporting evidence" icon="📄" />
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <Btn
                size="sm"
                variant={mode === "paste" ? "primary" : "secondary"}
                onClick={() => setMode("paste")}
              >
                Paste Text
              </Btn>
              <Btn
                size="sm"
                variant={mode === "upload" ? "primary" : "secondary"}
                onClick={() => setMode("upload")}
              >
                Upload File
              </Btn>
            </div>

            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Title (optional)
              </label>
              <input
                type="text"
                placeholder="e.g. Final Year Project Report"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                style={inputStyle}
              />
            </div>

            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Evidence type
              </label>
              <div style={{ display: "flex", gap: 8 }}>
                <Btn
                  size="sm"
                  variant={sourceType === "document" ? "primary" : "secondary"}
                  onClick={() => setSourceType("document")}
                >
                  Report / Explanation
                </Btn>
                <Btn
                  size="sm"
                  variant={sourceType === "certificate_transcript" ? "primary" : "secondary"}
                  onClick={() => setSourceType("certificate_transcript")}
                >
                  Certificate / Transcript
                </Btn>
              </div>
              {mode === "upload" && sourceType === "certificate_transcript" && (
                <p style={{ fontSize: 11, color: TOKEN.muted, marginTop: 6 }}>
                  We&apos;ll scan the uploaded file for certificate/transcript details (issuer, title, date).
                </p>
              )}
            </div>

            {mode === "paste" ? (
              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                  Pasted text *
                </label>
                <textarea
                  placeholder="Paste your project report, explanation, or certificate text here…"
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  rows={6}
                  style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
                />
              </div>
            ) : (
              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                  Document file (PDF, DOCX, TXT, or MD) *
                </label>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  style={{ fontSize: 13 }}
                />
              </div>
            )}

            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Claimed Skills (comma-separated, optional)
              </label>
              <input
                type="text"
                placeholder="React, TypeScript, Data Analysis"
                value={claimedSkills}
                onChange={(e) => setClaimedSkills(e.target.value)}
                style={inputStyle}
              />
            </div>

            <div>
              <label style={{ fontSize: 12, fontWeight: 600, color: TOKEN.inkSoft, display: "block", marginBottom: 4 }}>
                Description / objective (optional)
              </label>
              <textarea
                placeholder="What is this document and what does it show?"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
              />
            </div>

            {submitError && (
              <p style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, padding: "8px 10px", borderRadius: 6 }}>
                {submitError}
              </p>
            )}

            <div style={{ display: "flex", gap: 8 }}>
              <Btn variant="primary" onClick={handleSubmit} disabled={submitting}>
                {submitting ? "Submitting…" : "Submit"}
              </Btn>
              <Btn variant="secondary" onClick={() => setShowForm(false)}>Cancel</Btn>
            </div>
          </div>
        </Card>
      )}

      {loading && <LoadingState label="Loading document proofs…" />}
      {error && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && proofs.length === 0 && (
        <EmptyState
          icon="📄"
          title="No document proofs yet"
          description="Add a project report, certificate, or transcript as supporting evidence for your skills."
          action={<Btn variant="primary" onClick={() => setShowForm(true)}>Add your first document</Btn>}
        />
      )}

      {proofs.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {proofs.map((p) => (
            <DocumentProofCard key={p.id} proof={p} syncStatus={syncState[p.id]} onSync={runSync} onAttached={load} />
          ))}
        </div>
      )}

      <p style={{ fontSize: 11, color: TOKEN.muted, textAlign: "center", marginTop: 4 }}>
        Documents are supporting evidence only — they never count as fully verified proof.
      </p>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  border: `1px solid ${TOKEN.line}`,
  borderRadius: 8,
  fontSize: 13,
  background: TOKEN.paper,
  boxSizing: "border-box",
}
