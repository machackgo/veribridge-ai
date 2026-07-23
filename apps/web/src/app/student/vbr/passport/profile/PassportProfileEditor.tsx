"use client"

/**
 * Passport Profile editor — the student-facing control panel for the identity
 * shown on the PUBLIC Work Passport (name, photo, headline, education, links,
 * availability). Backed by GET/PUT /api/v1/student/vbr/passport/profile.
 *
 * Product rules implemented here:
 *  - every field optional; empty fields are omitted publicly (no placeholders)
 *  - prefill suggestions from existing account data are editor-only hints the
 *    student must explicitly accept — nothing is auto-published
 *  - visibility toggles for location / links / availability; work
 *    authorization is opt-in and OFF by default
 *  - live preview mirrors the public hero so the student sees exactly what a
 *    recruiter will see before saving
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"

import {
  PASSPORT_AVAILABILITY_OPTIONS,
  PASSPORT_PHOTO_ACCEPT,
  getPassportProfile,
  getWorkPassportStatus,
  removePassportPhoto,
  updatePassportProfile,
  uploadPassportPhoto,
  validatePassportPhoto,
  type PassportProfile,
  type PassportProfilePrefill,
  type PassportProfileUpdate,
} from "@/lib/vbr-api"
import {
  Badge,
  Card,
  ErrorState,
  LoadingState,
  TOKEN,
} from "../../../../../../components/passport/shared"

type FormState = {
  full_name: string
  preferred_name: string
  pronunciation: string
  headline: string
  bio: string
  institution: string
  degree: string
  graduation_year: string
  location: string
  github_url: string
  linkedin_url: string
  portfolio_url: string
  role_areas: string[]
  availability: string
  work_authorization_note: string
  show_location: boolean
  show_availability: boolean
  show_links: boolean
  show_work_authorization: boolean
}

const EMPTY_FORM: FormState = {
  full_name: "",
  preferred_name: "",
  pronunciation: "",
  headline: "",
  bio: "",
  institution: "",
  degree: "",
  graduation_year: "",
  location: "",
  github_url: "",
  linkedin_url: "",
  portfolio_url: "",
  role_areas: [],
  availability: "",
  work_authorization_note: "",
  show_location: true,
  show_availability: true,
  show_links: true,
  show_work_authorization: false,
}

function toForm(profile: PassportProfile): FormState {
  return {
    full_name: profile.full_name ?? "",
    preferred_name: profile.preferred_name ?? "",
    pronunciation: profile.pronunciation ?? "",
    headline: profile.headline ?? "",
    bio: profile.bio ?? "",
    institution: profile.institution ?? "",
    degree: profile.degree ?? "",
    graduation_year: profile.graduation_year ? String(profile.graduation_year) : "",
    location: profile.location ?? "",
    github_url: profile.github_url ?? "",
    linkedin_url: profile.linkedin_url ?? "",
    portfolio_url: profile.portfolio_url ?? "",
    role_areas: profile.role_areas ?? [],
    availability: profile.availability ?? "",
    work_authorization_note: profile.work_authorization_note ?? "",
    show_location: profile.show_location,
    show_availability: profile.show_availability,
    show_links: profile.show_links,
    show_work_authorization: profile.show_work_authorization,
  }
}

/** Only the fields that differ from the saved form are sent (PATCH). */
function diffForm(saved: FormState, current: FormState): PassportProfileUpdate {
  const update: Record<string, unknown> = {}
  const keys = Object.keys(current) as (keyof FormState)[]
  for (const key of keys) {
    const a = saved[key]
    const b = current[key]
    const equal = Array.isArray(a) && Array.isArray(b)
      ? a.length === b.length && a.every((v, i) => v === b[i])
      : a === b
    if (equal) continue
    if (key === "graduation_year") {
      update[key] = b === "" ? null : Number(b)
    } else if (typeof b === "string") {
      update[key] = b.trim() === "" ? null : b
    } else {
      update[key] = b
    }
  }
  return update as PassportProfileUpdate
}

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full name",
  preferred_name: "Preferred name",
  pronunciation: "Name pronunciation",
  headline: "Professional headline",
  bio: "Short bio",
  institution: "University / institution",
  degree: "Degree or program",
  graduation_year: "Expected graduation year",
  location: "Location",
  github_url: "GitHub URL",
  linkedin_url: "LinkedIn URL",
  portfolio_url: "Portfolio URL",
  role_areas: "Preferred role areas",
  availability: "Availability",
  work_authorization_note: "Work authorization",
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  padding: "10px 12px",
  borderRadius: 10,
  border: `1px solid ${TOKEN.line}`,
  fontSize: 14,
  color: TOKEN.ink,
  background: TOKEN.paper,
  outline: "none",
}

function Field({
  label,
  hint,
  error,
  children,
  suggestion,
  onUseSuggestion,
}: {
  label: string
  hint?: string
  error?: string | null
  children: React.ReactNode
  suggestion?: string | null
  onUseSuggestion?: () => void
}) {
  return (
    <label style={{ display: "block", minWidth: 0 }}>
      <span style={{ display: "block", fontSize: 13, fontWeight: 600, color: TOKEN.inkSoft, marginBottom: 6 }}>
        {label}
      </span>
      {children}
      {suggestion && onUseSuggestion && (
        <button
          type="button"
          onClick={onUseSuggestion}
          style={{
            marginTop: 6,
            fontSize: 12,
            color: TOKEN.indigo,
            background: TOKEN.indigoSoft,
            border: "none",
            borderRadius: 8,
            padding: "4px 10px",
            cursor: "pointer",
            maxWidth: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          Use “{suggestion}”
        </button>
      )}
      {hint && !error && (
        <span style={{ display: "block", fontSize: 12, color: TOKEN.muted, marginTop: 6 }}>{hint}</span>
      )}
      {error && (
        <span data-testid="profile-field-error" style={{ display: "block", fontSize: 12, color: TOKEN.rose, marginTop: 6 }}>
          {error}
        </span>
      )}
    </label>
  )
}

function Toggle({
  checked,
  onChange,
  label,
  testId,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  testId?: string
}) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: TOKEN.inkSoft }}>
      <input
        type="checkbox"
        data-testid={testId}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ width: 16, height: 16, accentColor: TOKEN.indigo }}
      />
      {label}
    </label>
  )
}

function SectionTitle({ title, note }: { title: string; note?: string }) {
  return (
    <div style={{ margin: "4px 0 4px" }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TOKEN.ink }}>{title}</div>
      {note && <div style={{ fontSize: 12.5, color: TOKEN.muted, marginTop: 2 }}>{note}</div>}
    </div>
  )
}

/** Compact live preview of the public hero (mirrors PublicPassportView). */
function HeroPreview({ form, avatarUrl }: { form: FormState; avatarUrl: string | null }) {
  const initials = (form.full_name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
  const educationLine = [form.degree, form.institution].filter(Boolean).join(" · ")
  const metaLine = [
    form.graduation_year ? `Expected ${form.graduation_year}` : "",
    form.show_location ? form.location : "",
  ]
    .filter(Boolean)
    .join(" · ")
  const availability = PASSPORT_AVAILABILITY_OPTIONS.find((o) => o.value === form.availability)
  return (
    <div data-testid="profile-preview">
    <Card style={{ background: TOKEN.bg }}>
      <div style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: TOKEN.muted, marginBottom: 12 }}>
        Public preview
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: "50%",
            overflow: "hidden",
            flexShrink: 0,
            background: TOKEN.indigoSoft,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 20,
            color: TOKEN.indigo,
          }}
        >
          {avatarUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatarUrl} alt="Profile" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            initials || "•"
          )}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink }}>
            {form.full_name || <span style={{ color: TOKEN.muted, fontWeight: 500 }}>Add your name…</span>}
          </div>
          {form.headline && (
            <div style={{ fontSize: 13.5, color: TOKEN.inkSoft, marginTop: 2 }}>{form.headline}</div>
          )}
          {educationLine && (
            <div style={{ fontSize: 13, color: TOKEN.muted, marginTop: 2 }}>{educationLine}</div>
          )}
          {metaLine && <div style={{ fontSize: 12.5, color: TOKEN.muted, marginTop: 2 }}>{metaLine}</div>}
          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            {form.show_availability && availability?.value && (
              <Badge tone="emerald">{availability.label}</Badge>
            )}
            {form.show_links && form.github_url && <Badge tone="slate">GitHub</Badge>}
            {form.show_links && form.linkedin_url && <Badge tone="sky">LinkedIn</Badge>}
            {form.show_links && form.portfolio_url && <Badge tone="purple">Portfolio</Badge>}
          </div>
        </div>
      </div>
      {form.bio && (
        <p style={{ fontSize: 13.5, color: TOKEN.inkSoft, lineHeight: 1.6, margin: "12px 0 0" }}>{form.bio}</p>
      )}
    </Card>
    </div>
  )
}

export function PassportProfileEditor() {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saved, setSaved] = useState<FormState>(EMPTY_FORM)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [prefill, setPrefill] = useState<PassportProfilePrefill>({})
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [publicPath, setPublicPath] = useState<string | null>(null)
  const [isPublished, setIsPublished] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<{ field: string; message: string } | null>(null)
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [roleDraft, setRoleDraft] = useState("")
  const fileRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [res, status] = await Promise.all([
          getPassportProfile(),
          getWorkPassportStatus().catch(() => null),
        ])
        if (cancelled) return
        const initial = toForm(res.profile)
        setSaved(initial)
        setForm(initial)
        setPrefill(res.prefill ?? {})
        setAvatarUrl(res.avatar_url)
        setPublicPath(status?.public_path ?? null)
        setIsPublished(Boolean(status?.is_published))
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Failed to load profile.")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const dirty = useMemo(
    () => Object.keys(diffForm(saved, form)).length > 0,
    [saved, form],
  )

  const set = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setSaveMessage(null)
    setFieldError((prev) => (prev && prev.field === key ? null : prev))
  }, [])

  const handleSave = useCallback(async () => {
    const update = diffForm(saved, form)
    if (Object.keys(update).length === 0) return
    setSaving(true)
    setSaveMessage(null)
    setFieldError(null)
    try {
      const res = await updatePassportProfile(update)
      const next = toForm(res.profile)
      setSaved(next)
      setForm(next)
      setSaveMessage(
        isPublished
          ? "Saved. Your public Passport shows these changes now."
          : "Saved. These details will appear when you publish your Passport.",
      )
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save profile."
      // Backend 422s carry "field" context inside the message body via
      // parseErrorMessage; match a known label when possible.
      const fieldKey = Object.keys(FIELD_LABELS).find((k) =>
        message.toLowerCase().includes(k.replace(/_/g, " ")),
      )
      setFieldError({ field: fieldKey ?? "", message })
    } finally {
      setSaving(false)
    }
  }, [saved, form, isPublished])

  const handlePhotoPick = useCallback(async (file: File | null) => {
    if (!file) return
    const invalid = validatePassportPhoto(file)
    if (invalid) {
      setPhotoError(invalid)
      return
    }
    setPhotoBusy(true)
    setPhotoError(null)
    try {
      const res = await uploadPassportPhoto(file)
      if (res.avatar_url) {
        setAvatarUrl(res.avatar_url)
      } else {
        setAvatarUrl(URL.createObjectURL(file))
        if (!res.persisted) setPhotoError("Photo preview is device-local — storage is not configured.")
      }
    } catch (err) {
      setPhotoError(err instanceof Error ? err.message : "Failed to upload photo.")
    } finally {
      setPhotoBusy(false)
    }
  }, [])

  const handlePhotoRemove = useCallback(async () => {
    setPhotoBusy(true)
    setPhotoError(null)
    try {
      await removePassportPhoto()
      setAvatarUrl(null)
    } catch (err) {
      setPhotoError(err instanceof Error ? err.message : "Failed to remove photo.")
    } finally {
      setPhotoBusy(false)
    }
  }, [])

  const addRoleArea = useCallback(() => {
    const text = roleDraft.trim()
    if (!text) return
    setForm((prev) =>
      prev.role_areas.includes(text) || prev.role_areas.length >= 6
        ? prev
        : { ...prev, role_areas: [...prev.role_areas, text] },
    )
    setRoleDraft("")
  }, [roleDraft])

  if (loading) return <LoadingState label="Loading your Passport Profile…" />
  if (loadError) return <ErrorState message={loadError} />

  const err = (field: string) => (fieldError?.field === field ? fieldError.message : null)
  const suggestionFor = (field: keyof PassportProfilePrefill, current: string) =>
    !current && prefill[field] ? String(prefill[field]) : null

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }} data-testid="passport-profile-editor">
      <HeroPreview form={form} avatarUrl={avatarUrl} />

      <Card>
        <SectionTitle
          title="Photo & identity"
          note="Shown at the top of your public Passport. Only add what you want recruiters to see."
        />
        <div style={{ display: "flex", gap: 16, alignItems: "center", margin: "14px 0 18px", flexWrap: "wrap" }}>
          <div
            style={{
              width: 72,
              height: 72,
              borderRadius: "50%",
              overflow: "hidden",
              background: TOKEN.indigoSoft,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            {avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={avatarUrl} alt="Profile" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            ) : (
              <span style={{ color: TOKEN.indigo, fontWeight: 700, fontSize: 22 }}>
                {(form.full_name || "?").slice(0, 1).toUpperCase()}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              ref={fileRef}
              type="file"
              accept={PASSPORT_PHOTO_ACCEPT.join(",")}
              style={{ display: "none" }}
              data-testid="profile-photo-input"
              onChange={(e) => handlePhotoPick(e.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={photoBusy}
              style={{
                padding: "8px 14px",
                borderRadius: 10,
                border: `1px solid ${TOKEN.line}`,
                background: TOKEN.paper,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                color: TOKEN.inkSoft,
              }}
            >
              {photoBusy ? "Working…" : avatarUrl ? "Replace photo" : "Upload photo"}
            </button>
            {avatarUrl && (
              <button
                type="button"
                onClick={handlePhotoRemove}
                disabled={photoBusy}
                style={{
                  padding: "8px 14px",
                  borderRadius: 10,
                  border: `1px solid ${TOKEN.line}`,
                  background: TOKEN.paper,
                  fontSize: 13,
                  cursor: "pointer",
                  color: TOKEN.rose,
                }}
              >
                Remove
              </button>
            )}
          </div>
        </div>
        {photoError && (
          <div style={{ fontSize: 12.5, color: TOKEN.rose, marginBottom: 12 }}>{photoError}</div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
          <Field
            label="Full name"
            error={err("full_name")}
            suggestion={suggestionFor("full_name", form.full_name)}
            onUseSuggestion={() => set("full_name", prefill.full_name ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-full-name"
              value={form.full_name}
              onChange={(e) => set("full_name", e.target.value)}
              placeholder="e.g. Jordan Rivera"
              maxLength={120}
            />
          </Field>
          <Field label="Preferred name (optional)" error={err("preferred_name")}>
            <input
              style={inputStyle}
              value={form.preferred_name}
              onChange={(e) => set("preferred_name", e.target.value)}
              placeholder="What you go by"
              maxLength={120}
            />
          </Field>
          <Field label="Name pronunciation (optional)" error={err("pronunciation")}>
            <input
              style={inputStyle}
              value={form.pronunciation}
              onChange={(e) => set("pronunciation", e.target.value)}
              placeholder="e.g. jor-dan ri-VE-ra"
              maxLength={160}
            />
          </Field>
          <Field
            label="Professional headline"
            hint="One line under your name, e.g. “AI Engineer | M.S. in Artificial Intelligence”."
            error={err("headline")}
            suggestion={suggestionFor("headline", form.headline)}
            onUseSuggestion={() => set("headline", prefill.headline ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-headline"
              value={form.headline}
              onChange={(e) => set("headline", e.target.value)}
              placeholder="e.g. AI Engineer | Backend & ML"
              maxLength={160}
            />
          </Field>
        </div>
        <div style={{ marginTop: 16 }}>
          <Field
            label="Short bio"
            hint="2–4 lines about what you build and care about. Shown as your candidate summary."
            error={err("bio")}
          >
            <textarea
              style={{ ...inputStyle, minHeight: 96, resize: "vertical", fontFamily: "inherit" }}
              data-testid="profile-bio"
              value={form.bio}
              onChange={(e) => set("bio", e.target.value)}
              placeholder="e.g. I build evidence-backed ML systems and full-stack products…"
              maxLength={700}
            />
          </Field>
        </div>
      </Card>

      <Card>
        <SectionTitle title="Education & location" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginTop: 14 }}>
          <Field
            label="University / institution"
            error={err("institution")}
            suggestion={suggestionFor("institution", form.institution)}
            onUseSuggestion={() => set("institution", prefill.institution ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-institution"
              value={form.institution}
              onChange={(e) => set("institution", e.target.value)}
              placeholder="e.g. Worcester Polytechnic Institute"
              maxLength={160}
            />
          </Field>
          <Field
            label="Degree or program"
            error={err("degree")}
            suggestion={suggestionFor("degree", form.degree)}
            onUseSuggestion={() => set("degree", prefill.degree ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-degree"
              value={form.degree}
              onChange={(e) => set("degree", e.target.value)}
              placeholder="e.g. M.S. in Artificial Intelligence"
              maxLength={120}
            />
          </Field>
          <Field label="Expected graduation year" error={err("graduation_year")}>
            <input
              style={inputStyle}
              data-testid="profile-graduation-year"
              value={form.graduation_year}
              onChange={(e) => set("graduation_year", e.target.value.replace(/[^0-9]/g, ""))}
              placeholder="e.g. 2027"
              inputMode="numeric"
              maxLength={4}
            />
          </Field>
          <Field
            label="Location (city/state)"
            hint="Broad location only — never a street address."
            error={err("location")}
            suggestion={suggestionFor("location", form.location)}
            onUseSuggestion={() => set("location", prefill.location ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-location"
              value={form.location}
              onChange={(e) => set("location", e.target.value)}
              placeholder="e.g. Worcester, Massachusetts"
              maxLength={120}
            />
          </Field>
        </div>
        <div style={{ marginTop: 14 }}>
          <Toggle
            checked={form.show_location}
            onChange={(v) => set("show_location", v)}
            label="Show my location on the public Passport"
            testId="toggle-show-location"
          />
        </div>
      </Card>

      <Card>
        <SectionTitle title="Public links" note="Plain https links only. GitHub and LinkedIn must be on their official domains." />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginTop: 14 }}>
          <Field
            label="GitHub URL"
            error={err("github_url")}
            suggestion={suggestionFor("github_url", form.github_url)}
            onUseSuggestion={() => set("github_url", prefill.github_url ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-github"
              value={form.github_url}
              onChange={(e) => set("github_url", e.target.value)}
              placeholder="https://github.com/username"
              maxLength={300}
            />
          </Field>
          <Field
            label="LinkedIn URL"
            error={err("linkedin_url")}
            suggestion={suggestionFor("linkedin_url", form.linkedin_url)}
            onUseSuggestion={() => set("linkedin_url", prefill.linkedin_url ?? "")}
          >
            <input
              style={inputStyle}
              data-testid="profile-linkedin"
              value={form.linkedin_url}
              onChange={(e) => set("linkedin_url", e.target.value)}
              placeholder="https://www.linkedin.com/in/username"
              maxLength={300}
            />
          </Field>
          <Field label="Portfolio URL (optional)" error={err("portfolio_url")}>
            <input
              style={inputStyle}
              data-testid="profile-portfolio"
              value={form.portfolio_url}
              onChange={(e) => set("portfolio_url", e.target.value)}
              placeholder="https://yoursite.dev"
              maxLength={300}
            />
          </Field>
        </div>
        <div style={{ marginTop: 14 }}>
          <Toggle
            checked={form.show_links}
            onChange={(v) => set("show_links", v)}
            label="Show my links on the public Passport"
            testId="toggle-show-links"
          />
        </div>
      </Card>

      <Card>
        <SectionTitle title="Preferences" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16, marginTop: 14 }}>
          <Field label="Availability" error={err("availability")}>
            <select
              style={{ ...inputStyle, appearance: "auto" }}
              data-testid="profile-availability"
              value={form.availability}
              onChange={(e) => set("availability", e.target.value)}
            >
              {PASSPORT_AVAILABILITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Preferred role areas (up to 6)"
            hint="Press Enter to add, e.g. “AI/ML”, “Backend”."
            error={err("role_areas")}
          >
            <input
              style={inputStyle}
              data-testid="profile-role-areas"
              value={roleDraft}
              onChange={(e) => setRoleDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault()
                  addRoleArea()
                }
              }}
              placeholder="Type a role area and press Enter"
              maxLength={80}
            />
            {form.role_areas.length > 0 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                {form.role_areas.map((area) => (
                  <span
                    key={area}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      background: TOKEN.indigoSoft,
                      color: TOKEN.indigo,
                      borderRadius: 999,
                      padding: "4px 10px",
                      fontSize: 12.5,
                    }}
                  >
                    {area}
                    <button
                      type="button"
                      aria-label={`Remove ${area}`}
                      onClick={() =>
                        set("role_areas", form.role_areas.filter((r) => r !== area))
                      }
                      style={{ border: "none", background: "none", cursor: "pointer", color: TOKEN.indigo, padding: 0, fontSize: 14, lineHeight: 1 }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </Field>
        </div>
        <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
          <Toggle
            checked={form.show_availability}
            onChange={(v) => set("show_availability", v)}
            label="Show availability on the public Passport"
            testId="toggle-show-availability"
          />
        </div>
      </Card>

      <Card>
        <SectionTitle
          title="Work authorization (optional)"
          note="Off by default. Only published if you explicitly turn it on — never inferred, never required."
        />
        <div style={{ marginTop: 14 }}>
          <Field label="Work authorization statement" error={err("work_authorization_note")}>
            <input
              style={inputStyle}
              data-testid="profile-work-auth"
              value={form.work_authorization_note}
              onChange={(e) => set("work_authorization_note", e.target.value)}
              placeholder="e.g. Authorized to work in the US"
              maxLength={200}
            />
          </Field>
          <div style={{ marginTop: 10 }}>
            <Toggle
              checked={form.show_work_authorization}
              onChange={(v) => set("show_work_authorization", v)}
              label="Publish this statement on my public Passport"
              testId="toggle-show-work-auth"
            />
          </div>
        </div>
      </Card>

      <div
        style={{
          position: "sticky",
          bottom: 12,
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
          background: TOKEN.paper,
          border: `1px solid ${TOKEN.line}`,
          borderRadius: 14,
          padding: "12px 16px",
          boxShadow: "0 8px 24px rgba(10,14,26,0.08)",
        }}
      >
        <button
          type="button"
          data-testid="profile-save"
          onClick={handleSave}
          disabled={!dirty || saving}
          style={{
            padding: "10px 20px",
            borderRadius: 10,
            border: "none",
            background: dirty ? TOKEN.indigo : "#c7cbe0",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: dirty ? "pointer" : "default",
          }}
        >
          {saving ? "Saving…" : "Save profile"}
        </button>
        {dirty && !saving && (
          <span style={{ fontSize: 12.5, color: TOKEN.amber }}>Unsaved changes</span>
        )}
        {saveMessage && (
          <span data-testid="profile-save-message" style={{ fontSize: 12.5, color: TOKEN.emerald }}>
            {saveMessage}
          </span>
        )}
        {fieldError && !fieldError.field && (
          <span style={{ fontSize: 12.5, color: TOKEN.rose }}>{fieldError.message}</span>
        )}
        <span style={{ flex: 1 }} />
        {isPublished && publicPath && (
          <a
            href={publicPath}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: 13, color: TOKEN.indigo, fontWeight: 600, textDecoration: "none" }}
          >
            Preview public Passport →
          </a>
        )}
        <Link
          href="/student/vbr/passport"
          style={{ fontSize: 13, color: TOKEN.muted, textDecoration: "none" }}
        >
          Back to Work Passport
        </Link>
      </div>
    </div>
  )
}
