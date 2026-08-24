"use client"

/**
 * Student Dashboard discovery card for the VeriBridge Website Proof Recorder
 * Chrome extension.
 *
 * Why this exists: Website Proof cannot be recorded without the extension, and
 * a new student had no way to learn that before hitting the recorder gate
 * mid-flow. This card answers WHY / WHAT / WHERE / WHAT-NEXT on the dashboard.
 *
 * Detection honesty: "detected" is rendered ONLY from a real content-script
 * bridge PONG (`probeRecorderExtension`). Clicking through to the Chrome Web
 * Store never changes this state. While the first probe is still in flight the
 * copy stays neutral ("Get Chrome extension") so a student who already has the
 * extension is never told to install it.
 *
 * Dashboard-level detection is architecturally valid here: the extension's
 * content script matches all https pages, and the recorder bridge answers the
 * synchronous ping on VeriBridge app origins (`/student` is a trusted app path
 * on localhost, and the whole production domain is trusted). No extension
 * change is required.
 */

import Link from "next/link"
import type { CSSProperties } from "react"

import { KeystoneMark } from "../brand"
import {
  RECORDER_EXTENSION_STORE_URL,
  detectRecorderBrowserSupport,
  isRecorderStoreListingLive,
} from "@/lib/recorder-extension-store"
import { emitInstallClicked, emitRecorderExtensionEvent } from "@/lib/recorder-extension-telemetry"
import { useRecorderExtensionDetection } from "@/lib/use-recorder-extension-detection"

const cardStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--paper)",
  padding: 18,
}

const chipStyle: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 6,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink-2)",
  fontSize: 12,
  fontFamily: "var(--font-mono)",
  whiteSpace: "nowrap",
}

const actionStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "8px 14px",
  borderRadius: 10,
  border: "1px solid var(--line)",
  background: "var(--bg-2)",
  color: "var(--ink)",
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
  cursor: "pointer",
}

const primaryStyle: CSSProperties = {
  ...actionStyle,
  background: "var(--ink)",
  color: "#fff",
  border: "1px solid var(--ink)",
}

const subtleLinkStyle: CSSProperties = {
  fontSize: 12,
  color: "var(--indigo)",
  textDecoration: "none",
  fontWeight: 600,
}

const detectedChip: CSSProperties = {
  ...chipStyle,
  background: "var(--emerald-soft)",
  borderColor: "#a7f3d0",
  color: "#065f46",
}

const warnChip: CSSProperties = {
  ...chipStyle,
  background: "var(--amber-soft)",
  borderColor: "#fde68a",
  color: "#92400e",
}

export function RecorderExtensionCard() {
  const browserSupport = detectRecorderBrowserSupport()
  const storeLive = isRecorderStoreListingLive()
  const unsupportedBrowser = browserSupport === "unsupported"
  // A browser that can't run the recorder can't answer the bridge either —
  // don't poll it, and never render an install/detection verdict for it.
  const { status, probe, checking, recheck, markInstallClicked } = useRecorderExtensionDetection({
    surface: "dashboard",
    enabled: !unsupportedBrowser,
  })

  const onInstallClick = () => {
    markInstallClicked()
    emitInstallClicked("dashboard", { reason: unsupportedBrowser ? "unsupported_browser" : status })
  }

  const effectiveStatus = unsupportedBrowser ? "unsupported" : status

  const statusChip =
    effectiveStatus === "unsupported"
      ? { style: warnChip, label: "Chrome required" }
      : effectiveStatus === "detected"
        ? {
            style: detectedChip,
            label: `✓ Recorder detected${probe?.build_version ? ` · v${probe.build_version}` : ""}`,
          }
        : effectiveStatus === "outdated"
          ? { style: warnChip, label: "Update required" }
          : effectiveStatus === "reload_needed"
            ? { style: warnChip, label: "Reconnect needed" }
            : effectiveStatus === "checking"
              ? { style: chipStyle, label: "Checking…" }
              : { style: chipStyle, label: "Not installed" }

  const installLabel =
    effectiveStatus === "outdated"
      ? "Update in Chrome Web Store"
      : effectiveStatus === "checking" || effectiveStatus === "unsupported"
        ? "Get Chrome extension"
        : "Install Chrome extension"

  const body =
    effectiveStatus === "unsupported"
      ? "Recording a Website Proof needs the recorder extension, which currently requires desktop Google Chrome (or another Chromium browser such as Microsoft Edge). Open VeriBridge on a desktop Chrome browser to record."
      : effectiveStatus === "detected"
        ? "The recorder is installed and ready. Start a Website Proof to record a workflow from your own project and attach it as evidence."
        : effectiveStatus === "outdated"
          ? "Your installed recorder is older than this app supports. Chrome updates extensions automatically within a few hours — or force it now from the store listing."
          : effectiveStatus === "reload_needed"
            ? "The recorder was updated or reloaded while this page was open, so its connection was lost. Refresh this page to reconnect it."
            : "Record real project workflows directly in Chrome and attach them as Website Proof evidence. The free recorder runs only while you record a proof you started."

  return (
    <div
      data-testid="dashboard-recorder-extension-card"
      data-recorder-status={effectiveStatus}
      style={{ ...cardStyle, display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 14 }}
    >
      <span
        aria-hidden="true"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 40,
          height: 40,
          borderRadius: 10,
          border: "1px solid var(--line)",
          background: "var(--bg-2)",
          flex: "0 0 auto",
        }}
      >
        <KeystoneMark size={22} />
      </span>

      <div style={{ flex: "1 1 260px", minWidth: 0 }}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)", margin: 0 }}>
            Website Proof Recorder
          </h3>
          <span
            data-testid="dashboard-recorder-status-chip"
            style={statusChip.style}
            aria-live="polite"
          >
            {statusChip.label}
          </span>
        </div>
        <p style={{ fontSize: 13, color: "var(--ink-2)", opacity: 0.85, margin: 0, lineHeight: 1.55 }}>{body}</p>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 10,
            marginTop: 12,
          }}
        >
          {effectiveStatus === "detected" ? (
            <>
              <Link
                href="/student/proofs/website"
                data-testid="dashboard-recorder-open-website-proof"
                style={primaryStyle}
              >
                Open Website Proof
              </Link>
              {storeLive && (
                <a
                  href={RECORDER_EXTENSION_STORE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="dashboard-recorder-store-link"
                  onClick={() => emitRecorderExtensionEvent("extension_listing_viewed", "dashboard")}
                  aria-label="View the Website Proof Recorder in the Chrome Web Store — opens in a new tab"
                  style={subtleLinkStyle}
                >
                  View in Chrome Web Store ↗
                </a>
              )}
            </>
          ) : effectiveStatus === "reload_needed" ? (
            <button
              type="button"
              data-testid="dashboard-recorder-refresh"
              onClick={() => window.location.reload()}
              style={primaryStyle}
            >
              Refresh this page
            </button>
          ) : storeLive ? (
            <a
              href={RECORDER_EXTENSION_STORE_URL}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="dashboard-recorder-install-link"
              onClick={onInstallClick}
              aria-label={`${installLabel} — opens the Chrome Web Store in a new tab`}
              style={primaryStyle}
            >
              {installLabel}
              <span aria-hidden="true">↗</span>
            </a>
          ) : (
            <span
              data-testid="dashboard-recorder-pending-release"
              style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}
            >
              The Chrome Web Store listing is not available right now.
            </span>
          )}

          {!unsupportedBrowser && effectiveStatus !== "detected" && effectiveStatus !== "reload_needed" && (
            <button
              type="button"
              data-testid="dashboard-recorder-recheck"
              onClick={recheck}
              disabled={checking}
              style={{ ...actionStyle, opacity: checking ? 0.6 : 1, cursor: checking ? "default" : "pointer" }}
            >
              {checking ? "Checking…" : "I've installed it — check again"}
            </button>
          )}

          <Link href="/extension" style={subtleLinkStyle}>
            Installation help
          </Link>
        </div>

        {effectiveStatus === "outdated" && probe?.build_version && (
          <p style={{ fontSize: 12, color: "#92400e", margin: "8px 0 0" }}>
            Detected v{probe.build_version} — an update is required before recording.
          </p>
        )}
      </div>
    </div>
  )
}
