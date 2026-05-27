"use client"

import { useEffect, useState } from "react"
import {
  listAdminRequesterProfiles,
  updateAdminRequesterVerification,
  type RecruiterRequesterProfileResponse,
} from "@/lib/passport-api"
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
} from "../passport/shared"

const VERIFICATION_STATUS_OPTIONS = [
  "unverified",
  "email_pending",
  "email_verified",
  "domain_verified",
  "trusted",
  "suspicious",
  "blocked",
]

function verificationTone(status: string): "emerald" | "amber" | "rose" | "slate" | "indigo" {
  if (status === "trusted" || status === "domain_verified") return "emerald"
  if (status === "email_verified") return "indigo"
  if (status === "email_pending" || status === "unverified") return "amber"
  if (status === "suspicious" || status === "blocked") return "rose"
  return "slate"
}

function RequesterCard({
  profile,
  onUpdate,
}: {
  profile: RecruiterRequesterProfileResponse
  onUpdate: (updated: RecruiterRequesterProfileResponse) => void
}) {
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    verification_status: profile.verification_status,
    email_verified: profile.email_verified,
    domain_verified: profile.domain_verified,
    notes: profile.notes ?? "",
  })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await updateAdminRequesterVerification(profile.id, form)
      onUpdate(updated)
      setEditing(false)
    } catch {}
    setSaving(false)
  }

  return (
    <Card style={{ padding: "14px 16px" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div
          style={{
            width: 38,
            height: 38,
            borderRadius: 10,
            background: TOKEN.indigoSoft,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 16,
            flexShrink: 0,
          }}
        >
          🧑‍💼
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
            <span style={{ fontWeight: 700, fontSize: 14, color: TOKEN.ink }}>
              {profile.name ?? profile.email}
            </span>
            <Badge tone={verificationTone(profile.verification_status)}>
              {profile.verification_status.replace(/_/g, " ")}
            </Badge>
            {profile.requester_type && <Badge tone="slate">{profile.requester_type}</Badge>}
          </div>

          <p style={{ fontSize: 12, color: TOKEN.muted, margin: "0 0 6px" }}>
            {profile.email}
            {profile.organization ? ` · ${profile.organization}` : ""}
            {profile.domain ? ` · @${profile.domain}` : ""}
          </p>

          <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
            <Badge tone={profile.email_verified ? "emerald" : "slate"}>
              {profile.email_verified ? "✓ Email verified" : "○ Email unverified"}
            </Badge>
            <Badge tone={profile.domain_verified ? "emerald" : "slate"}>
              {profile.domain_verified ? "✓ Domain verified" : "○ Domain unverified"}
            </Badge>
          </div>

          {/* Risk flags */}
          {profile.risk_flags.length > 0 && (
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 6 }}>
              {profile.risk_flags.map((flag: string) => (
                <Badge key={flag} tone="rose">⚠ {flag}</Badge>
              ))}
            </div>
          )}

          {profile.notes && !editing && (
            <p style={{ fontSize: 11, color: TOKEN.muted, fontStyle: "italic" }}>Note: {profile.notes}</p>
          )}

          {/* Edit form */}
          {editing && (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 8, alignItems: "center" }}>
                <select
                  value={form.verification_status}
                  onChange={(e) => setForm((f) => ({ ...f, verification_status: e.target.value }))}
                  style={{ padding: "7px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12 }}
                >
                  {VERIFICATION_STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                  ))}
                </select>
                <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={form.email_verified}
                    onChange={(e) => setForm((f) => ({ ...f, email_verified: e.target.checked }))}
                  />
                  Email verified
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={form.domain_verified}
                    onChange={(e) => setForm((f) => ({ ...f, domain_verified: e.target.checked }))}
                  />
                  Domain verified
                </label>
              </div>
              <input
                type="text"
                placeholder="Admin notes (optional)…"
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                style={{ padding: "7px 10px", border: `1px solid ${TOKEN.line}`, borderRadius: 7, fontSize: 12 }}
              />
              <div style={{ display: "flex", gap: 6 }}>
                <Btn size="sm" variant="primary" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving…" : "Save"}
                </Btn>
                <Btn size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Btn>
              </div>
            </div>
          )}

          <Mono style={{ fontSize: 10, color: TOKEN.muted, marginTop: 6, display: "block" }}>
            Last seen: {profile.last_seen_at ? new Date(profile.last_seen_at).toLocaleDateString() : "—"}
          </Mono>
        </div>

        {!editing && (
          <Btn size="sm" variant="secondary" onClick={() => setEditing(true)}>
            Update
          </Btn>
        )}
      </div>
    </Card>
  )
}

export function AdminRequesterVerificationPanel() {
  const [profiles, setProfiles] = useState<RecruiterRequesterProfileResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>("all")

  const load = () => {
    setLoading(true)
    setError(null)
    listAdminRequesterProfiles({ limit: 100 })
      .then(setProfiles)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleUpdate = (updated: RecruiterRequesterProfileResponse) => {
    setProfiles((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
  }

  const filtered = statusFilter === "all"
    ? profiles
    : profiles.filter((p) => p.verification_status === statusFilter)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: TOKEN.ink, margin: 0 }}>Requester Verification</h2>
          <p style={{ fontSize: 13, color: TOKEN.muted, margin: "4px 0 0" }}>
            Review and update recruiter/requester identity verification.
          </p>
        </div>
        <Btn variant="secondary" size="sm" onClick={load}>Refresh</Btn>
      </div>

      {/* Status filter */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {["all", "unverified", "email_verified", "domain_verified", "trusted", "suspicious", "blocked"].map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            type="button"
            style={{
              padding: "5px 12px",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${statusFilter === f ? TOKEN.indigo : TOKEN.line}`,
              background: statusFilter === f ? TOKEN.indigoSoft : TOKEN.paper,
              color: statusFilter === f ? TOKEN.indigo : TOKEN.muted,
              cursor: "pointer",
            }}
          >
            {f.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {loading && <LoadingState label="Loading profiles…" />}
      {error && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          icon="🧑‍💼"
          title="No profiles"
          description="No requester profiles match this filter."
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {filtered.map((p) => (
            <RequesterCard key={p.id} profile={p} onUpdate={handleUpdate} />
          ))}
        </div>
      )}
    </div>
  )
}
