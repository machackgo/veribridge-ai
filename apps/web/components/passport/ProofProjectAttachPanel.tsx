"use client"

/**
 * ProofProjectAttachPanel — the ONE shared, explicit proof→project attachment
 * control for standalone proof studios (GitHub Proof, Document Proof).
 *
 * Three explicit states, mirroring the canonical product contract:
 *   A. Attach to an existing owned project (student selects it).
 *   B. Create a new project, then attach (canonical project row is persisted
 *      FIRST via the projects endpoint, then the proof is finalized against it).
 *   C. Keep in Proof Vault only — the default; nothing is mutated.
 *
 * Every attachment flows through the shared canonical finalization boundary
 * (`confirmProofProjectRelationship` → `finalize_proof_evidence`), so a GitHub
 * or Document proof earns Passport / Project Report visibility exactly the way
 * a Website Proof does. Nothing here infers a project from proof metadata —
 * prefills are visible, editable suggestions the student must explicitly
 * confirm.
 */

import { useEffect, useState } from "react"
import {
  confirmProofProjectRelationship,
  createVBRProject,
  listVBRProjects,
  type VBRProjectResponse,
} from "@/lib/vbr-api"
import { Badge, Mono, TOKEN } from "./shared"

type AttachMode = "vault" | "existing" | "create"

const PROOF_TYPE_LABEL: Record<string, string> = {
  github: "GitHub Proof",
  document: "Document Proof",
}

/** Honest, proof-type-specific confirmation copy — what attaching does and
 *  does NOT claim. GitHub copy never implies authorship. */
function confirmationCopy(proofType: string, projectTitle: string): string {
  if (proofType === "github") {
    return (
      `I confirm this repository belongs to my project "${projectTitle}". ` +
      "Analyzed code evidence will count for that project's skills. This records the " +
      "repository as project evidence — it does not by itself claim I authored the code."
    )
  }
  return (
    `I confirm this document belongs to my project "${projectTitle}". ` +
    "Only its exactly-cited evidence (pages, sections, tables, code blocks) will count " +
    "for that project's skills."
  )
}

export function ProofProjectAttachPanel({
  proofType,
  proofId,
  relationshipState,
  attachedProjectTitle,
  defaultProjectTitle,
  defaultRepoUrl,
  onAttached,
}: {
  proofType: "github" | "document"
  proofId: string
  /** Canonical relationship state from the proof list payload. */
  relationshipState?: string | null
  attachedProjectTitle?: string | null
  /** Editable prefill for the create-new-project title (never auto-submitted). */
  defaultProjectTitle?: string
  /** Editable prefill for the create-new-project repo URL (never auto-submitted). */
  defaultRepoUrl?: string
  onAttached: (projectTitle: string) => void | Promise<void>
}) {
  const [mode, setMode] = useState<AttachMode>("vault")
  const [projects, setProjects] = useState<VBRProjectResponse[] | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [selectedProjectId, setSelectedProjectId] = useState("")
  const [newTitle, setNewTitle] = useState(defaultProjectTitle ?? "")
  const [newRepoUrl, setNewRepoUrl] = useState(defaultRepoUrl ?? "")
  const [confirmed, setConfirmed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const proofLabel = PROOF_TYPE_LABEL[proofType] ?? "Proof"

  // Owned projects load once the student opens a project-bound mode.
  useEffect(() => {
    if (mode === "vault" || projects !== null) return
    listVBRProjects()
      .then(setProjects)
      .catch((err: unknown) =>
        setProjectsError(err instanceof Error ? err.message : "Failed to load your projects."),
      )
  }, [mode, projects])

  // Already directly linked — show the honest state, never a second attach UI.
  if (relationshipState === "directly_linked") {
    return (
      <div data-testid="proof-attach-panel" data-state="attached" style={{ marginTop: 10 }}>
        <Badge tone="emerald">
          Attached to {attachedProjectTitle || "your project"} — counted in that project&apos;s report
        </Badge>
      </div>
    )
  }

  const selectedProject = projects?.find((p) => p.id === selectedProjectId) ?? null
  const targetTitle =
    mode === "existing" ? selectedProject?.title ?? "" : mode === "create" ? newTitle.trim() : ""
  const canSubmit =
    !submitting &&
    confirmed &&
    (mode === "existing"
      ? Boolean(selectedProject)
      : mode === "create"
        ? Boolean(newTitle.trim()) && Boolean(newRepoUrl.trim())
        : false)

  const changeMode = (next: AttachMode) => {
    setMode(next)
    setConfirmed(false)
    setError(null)
  }

  const submit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      let projectId = selectedProject?.id ?? ""
      let projectTitle = selectedProject?.title ?? ""
      if (mode === "create") {
        // The canonical project row is persisted FIRST; only then is the proof
        // finalized against it. Both steps are explicit owner actions.
        const project = await createVBRProject({
          title: newTitle.trim(),
          repo_url: newRepoUrl.trim(),
        })
        projectId = project.id
        projectTitle = project.title
      }
      await confirmProofProjectRelationship({
        proof_type: proofType,
        proof_id: proofId,
        project_id: projectId,
      })
      await onAttached(projectTitle)
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to attach this ${proofLabel}.`)
    } finally {
      setSubmitting(false)
    }
  }

  const radioStyle = { display: "flex", alignItems: "flex-start", gap: 7, fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.45, cursor: "pointer" } as const
  const inputStyle = {
    width: "100%",
    padding: "8px 10px",
    border: `1px solid ${TOKEN.line}`,
    borderRadius: 7,
    fontSize: 12,
    background: "#fff",
    boxSizing: "border-box",
  } as const

  return (
    <div
      data-testid="proof-attach-panel"
      data-proof-type={proofType}
      data-state="unattached"
      style={{
        marginTop: 12,
        display: "flex",
        flexDirection: "column",
        gap: 9,
        padding: 12,
        border: `1px solid ${TOKEN.line}`,
        borderRadius: 10,
        background: TOKEN.bg,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Mono style={{ fontSize: 10, color: TOKEN.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
          Project relationship
        </Mono>
        <span style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>
          This {proofLabel} is in your Proof Vault. It appears in the Work Passport project filter and
          Project Reports only after you explicitly attach it to one of your projects.
        </span>
      </div>

      <label style={radioStyle}>
        <input
          type="radio"
          name={`attach-mode-${proofId}`}
          data-testid="proof-attach-mode-vault"
          checked={mode === "vault"}
          disabled={submitting}
          onChange={() => changeMode("vault")}
        />
        <span>
          <strong style={{ color: TOKEN.ink }}>Keep in Proof Vault only.</strong> Nothing changes — this
          proof stays visible under its skills but is not counted for any project.
        </span>
      </label>

      <label style={radioStyle}>
        <input
          type="radio"
          name={`attach-mode-${proofId}`}
          data-testid="proof-attach-mode-existing"
          checked={mode === "existing"}
          disabled={submitting}
          onChange={() => changeMode("existing")}
        />
        <span>
          <strong style={{ color: TOKEN.ink }}>Attach to one of my existing projects.</strong>
        </span>
      </label>
      {mode === "existing" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, paddingLeft: 22 }}>
          {projectsError && (
            <span role="alert" style={{ fontSize: 11, color: TOKEN.rose }}>{projectsError}</span>
          )}
          {!projectsError && projects === null && (
            <span style={{ fontSize: 11, color: TOKEN.muted }}>Loading your projects…</span>
          )}
          {projects !== null && projects.length === 0 && (
            <span data-testid="proof-attach-no-projects" style={{ fontSize: 11, color: TOKEN.muted }}>
              You have no projects yet — choose “Create a new project” below.
            </span>
          )}
          {projects !== null && projects.length > 0 && (
            <select
              data-testid="proof-attach-project-select"
              value={selectedProjectId}
              disabled={submitting}
              onChange={(e) => {
                setSelectedProjectId(e.target.value)
                setConfirmed(false)
                setError(null)
              }}
              style={{ padding: "7px 8px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, background: "#fff", fontSize: 12 }}
            >
              <option value="">Select one of your projects…</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.title}
                  {project.repo_full_name ? ` · ${project.repo_full_name}` : ""}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      <label style={radioStyle}>
        <input
          type="radio"
          name={`attach-mode-${proofId}`}
          data-testid="proof-attach-mode-create"
          checked={mode === "create"}
          disabled={submitting}
          onChange={() => changeMode("create")}
        />
        <span>
          <strong style={{ color: TOKEN.ink }}>Create a new project and attach this proof to it.</strong>
        </span>
      </label>
      {mode === "create" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, paddingLeft: 22 }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11, color: TOKEN.inkSoft }}>
            Project title *
            <input
              type="text"
              data-testid="proof-attach-new-title"
              value={newTitle}
              disabled={submitting}
              placeholder="e.g. My Portfolio Pipeline"
              onChange={(e) => {
                setNewTitle(e.target.value)
                setConfirmed(false)
              }}
              style={inputStyle}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 11, color: TOKEN.inkSoft }}>
            GitHub repository URL *
            <input
              type="url"
              data-testid="proof-attach-new-repo"
              value={newRepoUrl}
              disabled={submitting}
              placeholder="https://github.com/owner/repo"
              onChange={(e) => {
                setNewRepoUrl(e.target.value)
                setConfirmed(false)
              }}
              style={inputStyle}
            />
          </label>
          <span style={{ fontSize: 10.5, color: TOKEN.muted, lineHeight: 1.5 }}>
            The project is created first, then this proof is attached to it. You confirm both below —
            nothing is created automatically.
          </span>
        </div>
      )}

      {(mode === "existing" || mode === "create") && targetTitle && (
        <label style={{ ...radioStyle, paddingLeft: 2 }}>
          <input
            type="checkbox"
            data-testid="proof-attach-confirm"
            checked={confirmed}
            disabled={submitting}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>{confirmationCopy(proofType, targetTitle)}</span>
        </label>
      )}

      {(mode === "existing" || mode === "create") && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            type="button"
            data-testid="proof-attach-submit"
            disabled={!canSubmit}
            onClick={submit}
            style={{
              alignSelf: "flex-start",
              padding: "7px 12px",
              border: "none",
              borderRadius: 7,
              background: !canSubmit ? "#cbd5e1" : TOKEN.indigo,
              color: "#fff",
              fontSize: 12,
              fontWeight: 700,
              cursor: !canSubmit ? "not-allowed" : "pointer",
            }}
          >
            {submitting
              ? "Attaching…"
              : mode === "create"
                ? "Create project & attach proof"
                : "Attach to selected project"}
          </button>
        </div>
      )}

      {error && (
        <p data-testid="proof-attach-error" role="alert" style={{ margin: 0, fontSize: 11, color: TOKEN.rose }}>
          {error}
        </p>
      )}
    </div>
  )
}
