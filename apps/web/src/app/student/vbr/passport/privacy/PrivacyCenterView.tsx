"use client"

/**
 * Privacy & Sharing center — the owner's layered disclosure control over the
 * public Work Passport.
 *
 * Layering (never a wall of checkboxes):
 *   1. Passport access — 🔒 Private / 🌍 Recruiter-safe / ⚙️ Custom mode cards.
 *   2. Effective public access summary — honest counts, zeros included.
 *   3. Presets (custom mode) — safe named bundles, never "expose everything".
 *   4. Per-project disclosure accordions (report / aspects / documents).
 *   5. Per-skill-group disclosure accordions (group / skill / project claim).
 *
 * All visibility truth is SERVER state: the component renders the backend's
 * configured/effective/allowed answers and submits changes as one reviewed
 * batch. It never computes what the public sees — only stages requests.
 * Destructive/expanding transitions (Private, Custom, presets, batch publish)
 * all pass through an explicit confirmation dialog with a busy-guard.
 */

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react"
import {
  applyDisclosureOverrides,
  applyDisclosurePreset,
  getDisclosureContext,
  publishWorkPassport,
  resetDisclosure,
  setDisclosureMode,
  unpublishWorkPassport,
  type DisclosureAspect,
  type DisclosureContext,
  type DisclosureDocument,
  type DisclosureOverrideChange,
  type DisclosurePreset,
  type DisclosureProject,
  type DisclosureSkillGroup,
} from "@/lib/vbr-api"
import {
  Badge,
  Card,
  ErrorState,
  LoadingState,
  Mono,
  TOKEN,
} from "../../../../../../components/passport/shared"

// ── Vocabulary ───────────────────────────────────────────────────────────────

const STATE_LABELS: Record<string, string> = {
  hidden: "Hidden",
  summary: "Summary",
  viewable: "Viewable",
  visible: "Visible",
  downloadable: "Downloadable",
}

function stateLabel(state: string | null | undefined): string {
  if (!state) return "Default"
  return STATE_LABELS[state] ?? state
}

/** Recruiter-facing wording for an effective state in the per-project one-liner. */
function effectiveWord(state: string): string {
  switch (state) {
    case "visible":
      return "Public"
    case "hidden":
      return "Hidden"
    case "summary":
      return "Summary only"
    case "viewable":
      return "Viewable"
    default:
      return STATE_LABELS[state] ?? state
  }
}

/** Ordered, honest exposure-summary rows (zeros render as "0" for trust). */
const SUMMARY_LABELS: [string, string][] = [
  ["projects_public", "projects"],
  ["skills_public", "skills"],
  ["skill_groups_public", "skill groups"],
  ["github_repositories_viewable", "GitHub repositories viewable"],
  ["exact_code_references", "exact code references"],
  ["websites_public", "websites"],
  ["website_screenshot_sets", "website screenshot sets"],
  ["website_recordings_viewable", "website recordings viewable"],
  ["document_summaries", "document summaries"],
  ["documents_viewable", "documents viewable"],
  ["document_downloads", "document downloads"],
  ["defense_summaries", "defense summaries"],
  ["defense_transcripts_viewable", "defense transcripts viewable"],
  ["defense_recordings_viewable", "defense recordings viewable"],
  ["video_moments_public", "video moments"],
]

function summaryLabel(key: string): string {
  const known = SUMMARY_LABELS.find(([k]) => k === key)
  return known ? known[1] : key.replace(/_/g, " ")
}

/** Ordered summary rows: the known vocabulary first, unknown keys appended. */
function orderedSummaryEntries(summary: Record<string, number>): [string, number][] {
  const ordered: [string, number][] = []
  for (const [key] of SUMMARY_LABELS) {
    if (key in summary) ordered.push([key, summary[key]])
  }
  for (const [key, value] of Object.entries(summary)) {
    if (!SUMMARY_LABELS.some(([k]) => k === key)) ordered.push([key, value])
  }
  return ordered
}

/** Bucket an aspect resource_type into its proof-family section. */
function aspectSection(resourceType: string): string {
  if (resourceType.startsWith("github")) return "GitHub"
  if (resourceType.startsWith("website")) return "Website"
  if (resourceType.startsWith("defense")) return "Defense"
  if (resourceType.startsWith("video")) return "Video"
  return "Other"
}

// ── Local pending-change model ───────────────────────────────────────────────

type PendingChange = {
  resource_type: string
  resource_key: string
  /** null = clear the override back to inherited. */
  visibility: string | null
  label: string
  fromLabel: string
  toLabel: string
}

const pendingKey = (resourceType: string, resourceKey: string) => `${resourceType}:${resourceKey}`

type ConfirmRequest = {
  title: string
  body: string
  content?: ReactNode
  confirmLabel: string
  danger?: boolean
  /** Resolves to the success status message. */
  action: () => Promise<string>
}

// ── Small module-level primitives (no accordion exists in the design system) ─

function Accordion({
  testId,
  header,
  children,
  defaultOpen = false,
}: {
  testId?: string
  header: ReactNode
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      data-testid={testId}
      style={{ border: `1px solid ${TOKEN.line}`, borderRadius: 12, background: "#fff", minWidth: 0 }}
    >
      <button
        type="button"
        aria-expanded={open}
        data-testid={testId ? `${testId}-toggle` : undefined}
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          textAlign: "left",
          display: "flex",
          alignItems: "flex-start",
          gap: 10,
          padding: 14,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          borderRadius: 12,
        }}
      >
        <span aria-hidden style={{ fontSize: 12, color: TOKEN.muted, marginTop: 2 }}>
          {open ? "▾" : "▸"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>{header}</div>
      </button>
      {open && <div style={{ padding: "0 14px 14px 14px" }}>{children}</div>}
    </div>
  )
}

function StateSegment({
  allowed,
  selected,
  disabled,
  onSelect,
  ariaLabel,
}: {
  allowed: string[]
  selected: string | null
  disabled: boolean
  onSelect: (state: string) => void
  ariaLabel: string
}) {
  return (
    <div role="group" aria-label={ariaLabel} style={{ display: "inline-flex", flexWrap: "wrap", gap: 4 }}>
      {allowed.map((state) => {
        const active = selected === state
        return (
          <button
            key={state}
            type="button"
            aria-pressed={active}
            disabled={disabled}
            data-state={state}
            onClick={() => onSelect(state)}
            style={{
              fontSize: 11.5,
              fontWeight: 600,
              padding: "5px 10px",
              borderRadius: 999,
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.55 : 1,
              border: `1px solid ${active ? TOKEN.indigo : TOKEN.line}`,
              background: active ? TOKEN.indigo : "#fff",
              color: active ? "#fff" : TOKEN.inkSoft,
            }}
          >
            {stateLabel(state)}
          </button>
        )
      })}
    </div>
  )
}

function ModeCard({
  testId,
  icon,
  title,
  tag,
  desc,
  active,
  disabled,
  onSelect,
}: {
  testId: string
  icon: string
  title: string
  tag?: string
  desc: string
  active: boolean
  disabled: boolean
  onSelect: () => void
}) {
  const style: CSSProperties = {
    textAlign: "left",
    display: "flex",
    flexDirection: "column",
    gap: 6,
    padding: 14,
    borderRadius: 12,
    cursor: disabled ? "wait" : "pointer",
    border: `2px solid ${active ? TOKEN.indigo : TOKEN.line}`,
    background: active ? TOKEN.indigoSoft : "#fff",
    minWidth: 0,
  }
  return (
    <button type="button" data-testid={testId} aria-pressed={active} disabled={disabled} onClick={onSelect} style={style}>
      <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span aria-hidden style={{ fontSize: 16 }}>{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: active ? TOKEN.indigo : TOKEN.ink }}>{title}</span>
        {tag && <Badge tone="emerald">{tag}</Badge>}
        {active && <Badge tone="indigo">Current</Badge>}
      </span>
      <span style={{ fontSize: 11.5, color: TOKEN.muted, lineHeight: 1.5 }}>{desc}</span>
    </button>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

export function PrivacyCenterView() {
  const [ctx, setCtx] = useState<DisclosureContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [pending, setPending] = useState<Map<string, PendingChange>>(new Map())
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [statusNote, setStatusNote] = useState<string | null>(null)
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null)

  const load = () => {
    setLoading(true)
    setLoadError(null)
    getDisclosureContext()
      .then((data) => setCtx(data))
      .catch((err: unknown) =>
        setLoadError(err instanceof Error ? err.message : "Failed to load privacy settings."),
      )
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  // Dialog focus + Escape-cancel (mirrors PassportVisibilityControl).
  useEffect(() => {
    if (confirm) confirmButtonRef.current?.focus()
  }, [confirm])
  useEffect(() => {
    if (!confirm) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) setConfirm(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [confirm, busy])

  const runConfirmed = () => {
    if (!confirm || busy) return // busy-guard: never double-submit
    setBusy(true)
    setActionError(null)
    confirm
      .action()
      .then((message) => {
        setStatusNote(message)
        setConfirm(null)
      })
      .catch((err: unknown) => {
        setActionError(
          err instanceof Error && err.message
            ? err.message
            : "The change didn't go through — nothing was modified. Please try again.",
        )
      })
      .finally(() => setBusy(false))
  }

  /** Run a server action directly (no dialog) with shared busy/error handling. */
  const runDirect = (action: () => Promise<string>) => {
    if (busy) return
    setBusy(true)
    setActionError(null)
    setStatusNote(null)
    action()
      .then((message) => setStatusNote(message))
      .catch((err: unknown) =>
        setActionError(err instanceof Error ? err.message : "The change didn't go through. Please try again."),
      )
      .finally(() => setBusy(false))
  }

  // ── pending helpers (defined before any early return — no hooks below) ─────

  /** The state a control should display: staged value wins over server state. */
  const displayState = (
    resourceType: string,
    resourceKey: string,
    configured: string | null,
    effective: string,
    defaultState?: string,
  ): string => {
    const p = pending.get(pendingKey(resourceType, resourceKey))
    if (p !== undefined) return p.visibility ?? defaultState ?? effective
    return configured ?? effective
  }

  const hasPending = (resourceType: string, resourceKey: string) =>
    pending.has(pendingKey(resourceType, resourceKey))

  const stage = (
    resourceType: string,
    resourceKey: string,
    visibility: string | null,
    label: string,
    configured: string | null,
    effective: string,
  ) => {
    setStatusNote(null)
    setPending((prev) => {
      const next = new Map(prev)
      const key = pendingKey(resourceType, resourceKey)
      // Staging back to the server's current configured value is a no-op.
      if (visibility === configured) {
        next.delete(key)
        return next
      }
      next.set(key, {
        resource_type: resourceType,
        resource_key: resourceKey,
        visibility,
        label,
        fromLabel: configured ? stateLabel(configured) : `Default (${stateLabel(effective)})`,
        toLabel: visibility ? stateLabel(visibility) : "Default",
      })
      return next
    })
  }

  if (loading) return <LoadingState label="Loading your privacy settings…" />
  if (loadError || !ctx) return <ErrorState message={loadError ?? "Privacy settings unavailable."} onRetry={load} />

  const passport = ctx.passport
  const currentMode: "private" | "recruiter_safe" | "custom" = !passport.is_published
    ? "private"
    : passport.mode
  const editable = passport.is_published && passport.mode === "custom" && !busy
  const previewPath = passport.public_path || passport.preview_public_path
  const summaryEntries = orderedSummaryEntries(ctx.summary)

  const disabledNote = !passport.is_published
    ? "Your Passport is Private — settings are kept but nothing is public."
    : passport.mode !== "custom"
      ? "Switch to Custom disclosure to change individual items."
      : null

  const afterServerChange = (next: DisclosureContext, message: string): string => {
    setCtx(next)
    setPending(new Map())
    return message
  }

  // ── mode actions ───────────────────────────────────────────────────────────

  const chooseMode = (target: "private" | "recruiter_safe" | "custom") => {
    if (busy || target === currentMode) return
    setStatusNote(null)
    setActionError(null)
    if (target === "private") {
      setConfirm({
        title: "Make your Passport private?",
        body:
          "This immediately blocks public access through your Passport link, Beam, QR code, public reports, and public skill-report links. Your granular disclosure settings are kept and apply again when you go public.",
        confirmLabel: "Make Passport Private",
        danger: true,
        action: async () => {
          await unpublishWorkPassport()
          const next = await getDisclosureContext()
          return afterServerChange(next, "Your Passport is now private. All public surfaces show a private-state page.")
        },
      })
      return
    }
    if (target === "recruiter_safe") {
      // Recommended, contracting change — no confirmation friction.
      runDirect(async () => {
        if (!passport.is_published) await publishWorkPassport()
        const next = await setDisclosureMode("recruiter_safe")
        return afterServerChange(
          next,
          "Your Passport is public with recruiter-safe defaults. Verified summaries are shown; originals stay private.",
        )
      })
      return
    }
    setConfirm({
      title: "Switch to custom disclosure?",
      body:
        "Your Passport will be public and you decide item by item what recruiters can inspect — repositories, screenshots, recordings, transcripts, and documents. Nothing extra is shared until you change it and publish.",
      confirmLabel: "Use Custom Disclosure",
      action: async () => {
        if (!passport.is_published) await publishWorkPassport()
        const next = await setDisclosureMode("custom")
        return afterServerChange(
          next,
          "Custom disclosure is on. Adjust individual items below, then review and publish your changes.",
        )
      },
    })
  }

  // ── preset actions ─────────────────────────────────────────────────────────

  const presets: { key: DisclosurePreset | "reset"; title: string; desc: string; confirmBody: string }[] = [
    {
      key: "recruiter_safe",
      title: "Recommended recruiter-safe",
      desc: "Verified summaries everywhere; originals stay private.",
      confirmBody: "Every item returns to the recruiter-safe default: verified summaries only, no originals.",
    },
    {
      key: "portfolio_open",
      title: "Portfolio-open",
      desc: "Share repositories, screenshots, and recordings where available.",
      confirmBody:
        "Attached repositories, screenshots, recordings, and documents become inspectable by recruiters. You can narrow any item afterwards.",
    },
    {
      key: "maximum_privacy",
      title: "Maximum privacy",
      desc: "Keep the Passport public but hide everything below the top-level summary.",
      confirmBody: "Everything below the top-level Passport summary is hidden from recruiters.",
    },
    {
      key: "reset",
      title: "Reset all overrides",
      desc: "Clear every custom override back to inherited defaults.",
      confirmBody: "All of your per-item overrides are removed and every item inherits its default again.",
    },
  ]

  const choosePreset = (preset: { key: DisclosurePreset | "reset"; title: string; confirmBody: string }) => {
    if (busy) return
    setStatusNote(null)
    setActionError(null)
    setConfirm({
      title: `Apply “${preset.title}”?`,
      body: preset.confirmBody,
      confirmLabel: "Apply",
      action: async () => {
        const next = preset.key === "reset" ? await resetDisclosure() : await applyDisclosurePreset(preset.key)
        return afterServerChange(next, `Applied “${preset.title}”. The public summary above reflects the new state.`)
      },
    })
  }

  // ── batch save ─────────────────────────────────────────────────────────────

  const reviewAndSave = () => {
    if (busy || pending.size === 0) return
    const changes = Array.from(pending.values())
    setConfirm({
      title: `Publish ${changes.length} privacy change${changes.length === 1 ? "" : "s"}?`,
      body: "These changes take effect on your public Passport immediately after publishing.",
      confirmLabel: "Publish changes",
      content: (
        <ul data-testid="privacy-review-list" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
          {changes.map((c) => (
            <li key={pendingKey(c.resource_type, c.resource_key)} style={{ fontSize: 12, color: TOKEN.inkSoft, lineHeight: 1.5 }}>
              <strong>{c.label}</strong>: {c.fromLabel} → {c.toLabel}
            </li>
          ))}
        </ul>
      ),
      action: async () => {
        const payload: DisclosureOverrideChange[] = changes.map(({ resource_type, resource_key, visibility }) => ({
          resource_type,
          resource_key,
          visibility,
        }))
        const next = await applyDisclosureOverrides(payload)
        setCtx(next)
        setPending(new Map())
        return `Published ${payload.length} privacy change${payload.length === 1 ? "" : "s"}. Your public Passport now reflects them.`
      },
    })
  }

  // ── row renderers (plain functions — never remounted component types) ──────

  const renderControlRow = (opts: {
    testId?: string
    label: string
    description?: string
    resourceType: string
    resourceKey: string
    allowed: string[]
    configured: string | null
    effective: string
    defaultState?: string
    available?: boolean
    effectiveNote?: string | null
    indent?: number
  }) => {
    const {
      testId,
      label,
      description,
      resourceType,
      resourceKey,
      allowed,
      configured,
      effective,
      defaultState,
      available = true,
      effectiveNote,
      indent = 0,
    } = opts
    const staged = pending.get(pendingKey(resourceType, resourceKey))
    const shown = displayState(resourceType, resourceKey, configured, effective, defaultState)
    const isCustomised = staged !== undefined ? staged.visibility !== null : configured !== null
    const controlsDisabled = !editable || !available
    return (
      <div
        key={`${resourceType}:${resourceKey}`}
        data-testid={testId}
        data-resource-key={resourceKey}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          padding: "10px 12px",
          marginLeft: indent,
          border: `1px solid ${TOKEN.line}`,
          borderRadius: 10,
          background: available ? "#fff" : TOKEN.bg,
          opacity: available ? 1 : 0.55,
          minWidth: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: TOKEN.ink, overflowWrap: "anywhere" }}>{label}</span>
          {!available && <Badge tone="slate">Not attached</Badge>}
          {available &&
            (isCustomised ? <Badge tone="indigo">Custom — modified</Badge> : <Badge tone="slate">Default</Badge>)}
          {available && (
            <Badge tone={shown === "hidden" ? "slate" : "emerald"}>
              {staged !== undefined ? `Pending: ${stateLabel(shown)}` : `Effective: ${stateLabel(effective)}`}
            </Badge>
          )}
        </div>
        {description && <p style={{ fontSize: 11.5, color: TOKEN.muted, margin: 0, lineHeight: 1.5 }}>{description}</p>}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <StateSegment
            allowed={allowed}
            selected={available ? shown : null}
            disabled={controlsDisabled}
            ariaLabel={`${label} visibility`}
            onSelect={(state) => {
              if (state === shown) return
              stage(resourceType, resourceKey, state, label, configured, effective)
            }}
          />
          {available && isCustomised && !controlsDisabled && (
            <button
              type="button"
              data-testid={testId ? `${testId}-use-default` : undefined}
              onClick={() => stage(resourceType, resourceKey, null, label, configured, effective)}
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: TOKEN.indigo,
                background: "transparent",
                border: "none",
                cursor: "pointer",
                padding: "4px 2px",
              }}
            >
              Use default
            </button>
          )}
        </div>
        {effectiveNote && (
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>{effectiveNote}</p>
        )}
      </div>
    )
  }

  const renderDocumentRow = (doc: DisclosureDocument) => {
    const shownState = displayState("document", doc.document_key, doc.configured, doc.effective, doc.default)
    const downloadStaged = pending.get(pendingKey("document_download", doc.document_key))
    const downloadable =
      downloadStaged !== undefined ? downloadStaged.visibility === "downloadable" : doc.effective_downloadable
    const docViewable = shownState === "viewable"
    const anyPending = downloadStaged !== undefined || hasPending("document", doc.document_key)
    const title = doc.title || "Untitled document"
    return (
      <div
        key={doc.document_key}
        data-testid="privacy-doc-row"
        data-document-key={doc.document_key}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          padding: "10px 12px",
          border: `1px solid ${TOKEN.line}`,
          borderRadius: 10,
          background: "#fff",
          minWidth: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12.5, fontWeight: 600, color: TOKEN.ink, overflowWrap: "anywhere" }}>📄 {title}</span>
          {anyPending ? (
            <Badge tone="indigo">Pending</Badge>
          ) : doc.configured !== null || doc.download_configured !== null ? (
            <Badge tone="indigo">Custom — modified</Badge>
          ) : (
            <Badge tone="slate">Default</Badge>
          )}
          <Badge tone={shownState === "hidden" ? "slate" : "emerald"}>
            {stateLabel(shownState)}
            {docViewable ? (downloadable ? " · Downloadable" : " · View only") : ""}
          </Badge>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <StateSegment
            allowed={doc.allowed}
            selected={shownState}
            disabled={!editable}
            ariaLabel={`${title} visibility`}
            onSelect={(state) => {
              if (state === shownState) return
              stage("document", doc.document_key, state, `Document “${title}”`, doc.configured, doc.effective)
            }}
          />
          <button
            type="button"
            data-testid="privacy-doc-download-toggle"
            aria-pressed={downloadable}
            disabled={!editable || !docViewable}
            title={
              docViewable
                ? downloadable
                  ? "Recruiters can download this document — switch to view-only."
                  : "Allow recruiters to download the original file."
                : "Downloads can only be allowed when the document is Viewable."
            }
            onClick={() =>
              stage(
                "document_download",
                doc.document_key,
                downloadable ? "hidden" : "downloadable",
                `Download “${title}”`,
                doc.download_configured,
                doc.effective_downloadable ? "downloadable" : "hidden",
              )
            }
            style={{
              fontSize: 11.5,
              fontWeight: 600,
              padding: "5px 10px",
              borderRadius: 999,
              cursor: !editable || !docViewable ? "not-allowed" : "pointer",
              opacity: !editable || !docViewable ? 0.55 : 1,
              border: `1px solid ${downloadable ? TOKEN.indigo : TOKEN.line}`,
              background: downloadable ? TOKEN.indigoSoft : "#fff",
              color: downloadable ? TOKEN.indigo : TOKEN.inkSoft,
            }}
          >
            {downloadable ? "Downloadable" : "Allow download"}
          </button>
        </div>
        {docViewable && !doc.has_retained_original && (
          <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>
            Original file not retained — summary shown.
          </p>
        )}
      </div>
    )
  }

  const projectHeaderSummary = (p: DisclosureProject): string => {
    const parts: string[] = [`Report: ${p.report.effective === "visible" ? "Public" : "Hidden"}`]
    const byType = (rt: string) => p.aspects.find((a) => a.resource_type === rt)
    const push = (label: string, aspect: DisclosureAspect | undefined) => {
      if (aspect?.available) parts.push(`${label}: ${effectiveWord(aspect.effective)}`)
    }
    push("GitHub", byType("github_repo"))
    push("Website", byType("website_summary"))
    if (p.documents.length > 0) {
      const counts: string[] = []
      const n = (state: string) => p.documents.filter((d) => d.effective === state).length
      if (n("viewable")) counts.push(`${n("viewable")} viewable`)
      if (n("summary")) counts.push(`${n("summary")} summary`)
      if (n("hidden")) counts.push(`${n("hidden")} hidden`)
      parts.push(`Documents: ${counts.join(", ")}`)
    }
    push("Defense", byType("defense_summary"))
    push("Video", byType("video_summary"))
    return parts.join(" · ")
  }

  const groupedAspects = (p: DisclosureProject): { section: string; aspects: DisclosureAspect[] }[] => {
    const sections: { section: string; aspects: DisclosureAspect[] }[] = []
    for (const aspect of p.aspects) {
      const section = aspectSection(aspect.resource_type)
      const bucket = sections.find((s) => s.section === section)
      if (bucket) bucket.aspects.push(aspect)
      else sections.push({ section, aspects: [aspect] })
    }
    return sections
  }

  const renderSkillGroup = (group: DisclosureSkillGroup) => {
    const groupShown = displayState("skill_group", group.category, group.configured, group.effective)
    const visibleSkillCount = group.skills.filter((s) => s.effective === "visible").length
    return (
      <Accordion
        key={group.category}
        testId="privacy-skill-group"
        header={
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13.5, fontWeight: 700, color: TOKEN.ink }}>{group.category}</span>
            <Badge tone={group.effective === "visible" ? "emerald" : "slate"}>
              {group.effective === "visible"
                ? `${visibleSkillCount} of ${group.skills.length} skills public`
                : "Hidden"}
            </Badge>
          </div>
        }
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {renderControlRow({
            testId: "privacy-aspect-skill_group",
            label: `Show the “${group.category}” group`,
            resourceType: "skill_group",
            resourceKey: group.category,
            allowed: group.allowed,
            configured: group.configured,
            effective: group.effective,
          })}
          {group.skills.map((skill) => {
            const skillShown = displayState("skill", skill.skill_slug, skill.configured, skill.effective)
            const skillNote =
              skillShown === "visible" && groupShown === "hidden"
                ? "Effective: Hidden because the skill group is hidden."
                : null
            return (
              <div key={skill.skill_slug} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {renderControlRow({
                  testId: "privacy-skill-row",
                  label: skill.skill,
                  resourceType: "skill",
                  resourceKey: skill.skill_slug,
                  allowed: skill.allowed,
                  configured: skill.configured,
                  effective: skill.effective,
                  effectiveNote: skillNote,
                  indent: 12,
                })}
                {skill.project_claims.map((claim) => {
                  const claimShown = displayState(
                    "project_skill",
                    claim.resource_key,
                    claim.configured,
                    claim.effective,
                  )
                  const claimNote =
                    claimShown === "visible" && (skillShown === "hidden" || groupShown === "hidden")
                      ? `Effective: Hidden because the ${groupShown === "hidden" ? "skill group" : "skill"} is hidden.`
                      : null
                  return renderControlRow({
                    testId: "privacy-claim-row",
                    label: `in ${claim.project_title}`,
                    resourceType: "project_skill",
                    resourceKey: claim.resource_key,
                    allowed: claim.allowed,
                    configured: claim.configured,
                    effective: claim.effective,
                    effectiveNote: claimNote,
                    indent: 28,
                  })
                })}
              </div>
            )
          })}
        </div>
      </Accordion>
    )
  }

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div data-testid="privacy-center" style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
      {/* 1 — Passport access */}
      <Card>
        <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 10 }}>
          Passport access
        </Mono>
        <div
          role="group"
          aria-label="Passport access mode"
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}
        >
          <ModeCard
            testId="privacy-mode-private"
            icon="🔒"
            title="Private"
            desc="Only you can see your Passport. Every public link and QR shows a private-state page."
            active={currentMode === "private"}
            disabled={busy}
            onSelect={() => chooseMode("private")}
          />
          <ModeCard
            testId="privacy-mode-recruiter_safe"
            icon="🌍"
            title="Public — Recruiter-safe"
            tag="Recommended"
            desc="Verified summaries for everything. Originals stay private."
            active={currentMode === "recruiter_safe"}
            disabled={busy}
            onSelect={() => chooseMode("recruiter_safe")}
          />
          <ModeCard
            testId="privacy-mode-custom"
            icon="⚙️"
            title="Public — Custom disclosure"
            desc="Choose what recruiters can inspect"
            active={currentMode === "custom"}
            disabled={busy}
            onSelect={() => chooseMode("custom")}
          />
        </div>

        {currentMode === "private" && (
          <p
            data-testid="privacy-private-banner"
            style={{
              margin: "12px 0 0",
              fontSize: 12,
              lineHeight: 1.6,
              color: TOKEN.inkSoft,
              background: TOKEN.bg,
              border: `1px solid ${TOKEN.line}`,
              borderRadius: 10,
              padding: "10px 12px",
            }}
          >
            🔒 Your Passport is Private. Your granular disclosure settings below are kept exactly as they are, but
            nothing is publicly visible until you switch back to Public.
          </p>
        )}

        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          {previewPath && (
            <a
              data-testid="privacy-preview-link"
              href={previewPath}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: TOKEN.indigo,
                textDecoration: "none",
                padding: "7px 12px",
                borderRadius: 8,
                border: `1px solid ${TOKEN.line}`,
                background: "#fff",
              }}
            >
              👁 Preview as recruiter ↗
            </a>
          )}
          <span style={{ fontSize: 11, color: TOKEN.muted }}>
            Hidden items never appear on the public Passport — recruiters see no trace of them.
          </span>
        </div>

        {statusNote && (
          <p data-testid="privacy-status" role="status" style={{ margin: "10px 0 0", fontSize: 12, color: "#047857", lineHeight: 1.5 }}>
            {statusNote}
          </p>
        )}
        {actionError && !confirm && (
          <p data-testid="privacy-error" role="alert" style={{ margin: "10px 0 0", fontSize: 12, color: TOKEN.rose, lineHeight: 1.5 }}>
            {actionError}
          </p>
        )}
      </Card>

      {/* 2 — Effective public access summary */}
      <Card>
        <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 10 }}>
          Effective public access
        </Mono>
        <p style={{ fontSize: 12.5, fontWeight: 600, color: TOKEN.ink, margin: "0 0 10px" }}>
          {passport.is_published
            ? "Your public Passport currently exposes:"
            : "If made Public, your Passport would expose:"}
        </p>
        <div
          data-testid="privacy-summary"
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 8 }}
        >
          {summaryEntries.map(([key, count]) => (
            <div
              key={key}
              data-testid="privacy-summary-row"
              data-summary-key={key}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 6,
                padding: "8px 10px",
                border: `1px solid ${TOKEN.line}`,
                borderRadius: 8,
                background: TOKEN.bg,
              }}
            >
              <strong style={{ fontSize: 15, color: count > 0 ? TOKEN.ink : TOKEN.muted }}>{count}</strong>
              <span style={{ fontSize: 11.5, color: TOKEN.muted, lineHeight: 1.4 }}>{summaryLabel(key)}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* 3 — Presets (custom mode only) */}
      {currentMode === "custom" && (
        <Card>
          <Mono style={{ fontSize: 10, letterSpacing: "0.14em", color: TOKEN.muted, textTransform: "uppercase", display: "block", marginBottom: 10 }}>
            Quick presets
          </Mono>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
            {presets.map((preset) => (
              <button
                key={preset.key}
                type="button"
                data-testid={`privacy-preset-${preset.key}`}
                disabled={busy}
                onClick={() => choosePreset(preset)}
                style={{
                  textAlign: "left",
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: `1px solid ${TOKEN.line}`,
                  background: "#fff",
                  cursor: busy ? "wait" : "pointer",
                }}
              >
                <span style={{ fontSize: 12.5, fontWeight: 700, color: TOKEN.ink }}>{preset.title}</span>
                <span style={{ fontSize: 11.5, color: TOKEN.muted, lineHeight: 1.5 }}>{preset.desc}</span>
              </button>
            ))}
          </div>
        </Card>
      )}

      {/* Recruiter-safe: controls shown but locked, with an inline mode-switch CTA */}
      {currentMode === "recruiter_safe" && (
        <p
          data-testid="privacy-locked-note"
          style={{
            margin: 0,
            fontSize: 12,
            color: TOKEN.inkSoft,
            lineHeight: 1.6,
            background: TOKEN.indigoSoft,
            border: `1px solid ${TOKEN.line}`,
            borderRadius: 10,
            padding: "10px 12px",
          }}
        >
          You are on recruiter-safe defaults. Individual controls below are shown for transparency but locked —{" "}
          <button
            type="button"
            data-testid="privacy-switch-to-custom"
            disabled={busy}
            onClick={() => chooseMode("custom")}
            style={{ fontSize: 12, fontWeight: 700, color: TOKEN.indigo, background: "transparent", border: "none", cursor: "pointer", padding: 0 }}
          >
            switch to Custom disclosure
          </button>{" "}
          to change individual items.
        </p>
      )}

      {/* 4 — Project disclosure */}
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Project disclosure</h2>
        {ctx.projects.length === 0 && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>No published projects yet.</p>
        )}
        {ctx.projects.map((project) => (
          <Accordion
            key={project.project_id}
            testId="privacy-project-card"
            header={
              <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13.5, fontWeight: 700, color: TOKEN.ink, overflowWrap: "anywhere" }}>
                    {project.title}
                  </span>
                  {project.override_count > 0 && <Badge tone="indigo">{project.override_count} custom</Badge>}
                </div>
                <span style={{ fontSize: 11.5, color: TOKEN.muted, lineHeight: 1.5 }}>
                  {projectHeaderSummary(project)}
                </span>
              </div>
            }
          >
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {renderControlRow({
                testId: "privacy-aspect-project",
                label: "Project on Passport",
                description: "Whether this project appears on your public Passport at all.",
                resourceType: "project",
                resourceKey: project.project_id,
                allowed: project.project.allowed,
                configured: project.project.configured,
                effective: project.project.effective,
              })}
              {renderControlRow({
                testId: "privacy-aspect-report",
                label: "Public project report",
                description: "The recruiter-safe Verified Build Report link for this project.",
                resourceType: "report",
                resourceKey: project.project_id,
                allowed: project.report.allowed,
                configured: project.report.configured,
                effective: project.report.effective,
              })}

              {groupedAspects(project).map(({ section, aspects }) => (
                <div key={section} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <Mono style={{ fontSize: 10, letterSpacing: "0.12em", color: TOKEN.muted, textTransform: "uppercase", marginTop: 4 }}>
                    {section}
                  </Mono>
                  {aspects.map((aspect) =>
                    renderControlRow({
                      testId: `privacy-aspect-${aspect.resource_type}`,
                      label: aspect.label,
                      description: aspect.description,
                      resourceType: aspect.resource_type,
                      resourceKey: aspect.resource_key,
                      allowed: aspect.allowed,
                      configured: aspect.configured,
                      effective: aspect.effective,
                      defaultState: aspect.default,
                      available: aspect.available,
                    }),
                  )}
                </div>
              ))}

              {project.documents.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <Mono style={{ fontSize: 10, letterSpacing: "0.12em", color: TOKEN.muted, textTransform: "uppercase", marginTop: 4 }}>
                    Documents
                  </Mono>
                  {project.documents.map((doc) => renderDocumentRow(doc))}
                </div>
              )}

              {disabledNote && (
                <p style={{ fontSize: 11, color: TOKEN.muted, margin: 0, fontStyle: "italic" }}>{disabledNote}</p>
              )}
            </div>
          </Accordion>
        ))}
      </section>

      {/* 5 — Skills disclosure */}
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Skills disclosure</h2>
        {ctx.skill_groups.length === 0 && (
          <p style={{ fontSize: 12, color: TOKEN.muted, margin: 0 }}>No skills on your Passport yet.</p>
        )}
        {ctx.skill_groups.map((group) => renderSkillGroup(group))}
      </section>

      {/* 6 — Unsaved-changes bar */}
      {pending.size > 0 && (
        <div
          data-testid="privacy-unsaved-bar"
          style={{
            position: "sticky",
            bottom: 12,
            zIndex: 30,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
            flexWrap: "wrap",
            padding: "12px 16px",
            borderRadius: 12,
            background: TOKEN.ink,
            color: "#fff",
            boxShadow: "0 12px 32px rgba(10,14,26,0.35)",
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 700 }}>
            {pending.size} unsaved change{pending.size === 1 ? "" : "s"}
          </span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid="privacy-discard"
              disabled={busy}
              onClick={() => setPending(new Map())}
              style={{
                fontSize: 12.5,
                fontWeight: 600,
                padding: "8px 14px",
                borderRadius: 9,
                border: "1px solid rgba(255,255,255,0.35)",
                background: "transparent",
                color: "#fff",
                cursor: busy ? "wait" : "pointer",
              }}
            >
              Discard
            </button>
            <button
              type="button"
              data-testid="privacy-save"
              disabled={busy}
              onClick={reviewAndSave}
              style={{
                fontSize: 12.5,
                fontWeight: 700,
                padding: "8px 14px",
                borderRadius: 9,
                border: "none",
                background: TOKEN.indigo,
                color: "#fff",
                cursor: busy ? "wait" : "pointer",
              }}
            >
              Review &amp; publish
            </button>
          </div>
        </div>
      )}

      {/* Confirmation dialog (shared by mode switches, presets, and batch save) */}
      {confirm && (
        <div
          data-testid="privacy-confirm-backdrop"
          onClick={() => {
            if (!busy) setConfirm(null)
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(15,23,42,0.45)",
            zIndex: 90,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="privacy-confirm-title"
            data-testid="privacy-confirm-dialog"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff",
              borderRadius: 14,
              border: `1px solid ${TOKEN.line}`,
              boxShadow: "0 18px 50px rgba(15,23,42,0.25)",
              padding: 20,
              width: "100%",
              maxWidth: 440,
              maxHeight: "80vh",
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <h3 id="privacy-confirm-title" style={{ margin: 0, fontSize: 16, fontWeight: 700, color: TOKEN.ink }}>
              {confirm.title}
            </h3>
            <p style={{ margin: 0, fontSize: 12.5, color: TOKEN.inkSoft, lineHeight: 1.6 }}>{confirm.body}</p>
            {confirm.content}
            {actionError && (
              <p
                data-testid="privacy-confirm-error"
                role="alert"
                style={{ fontSize: 12, color: TOKEN.rose, background: TOKEN.roseSoft, borderRadius: 8, padding: "8px 10px", margin: 0, lineHeight: 1.5 }}
              >
                {actionError}
              </p>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap", marginTop: 4 }}>
              <button
                type="button"
                data-testid="privacy-confirm-cancel"
                disabled={busy}
                onClick={() => setConfirm(null)}
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  padding: "9px 14px",
                  borderRadius: 9,
                  cursor: busy ? "wait" : "pointer",
                  border: `1px solid ${TOKEN.line}`,
                  background: "#fff",
                  color: TOKEN.inkSoft,
                }}
              >
                Cancel
              </button>
              <button
                ref={confirmButtonRef}
                type="button"
                data-testid="privacy-confirm-submit"
                disabled={busy}
                onClick={runConfirmed}
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  padding: "9px 14px",
                  borderRadius: 9,
                  cursor: busy ? "wait" : "pointer",
                  border: "none",
                  background: confirm.danger ? TOKEN.ink : TOKEN.indigo,
                  color: "#fff",
                  opacity: busy ? 0.7 : 1,
                }}
              >
                {busy ? "Working…" : confirm.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
