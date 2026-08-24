// Extension discovery + install UX coverage for the two entry points
// (student dashboard card, Website Proof surfaces) and the state distinction
// between "not installed" and "installed but something went wrong".
//
// The load-bearing guarantees under test:
//  - detection is never faked: clicking the store link cannot flip the card to
//    "detected"; only a correlated bridge PONG can,
//  - an installed extension is never told to install,
//  - runtime/connection failures never render installation messaging, and
//    WPR-DIFFERENT-SESSION-ACTIVE is never treated as one,
//  - unsupported browsers get no "ready to record" claim,
//  - external links are safe and point at the official listing.

import { describe, expect, it, vi, afterEach, beforeEach } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import React from "react"

import { RecorderExtensionCard } from "../../components/student/recorder-extension-card"
import {
  RecorderConnectionRecovery,
  isRecorderConnectionFailure,
} from "../../components/skill-proof/recorder-connection-recovery"
import { RecorderReadyBadge } from "../../components/skill-proof/recorder-ready-badge"
import { recorderGateReasonFor } from "../../components/skill-proof/recorder-install-gate"
import { VERIBRIDGE_CHROME_EXTENSION_URL } from "@/lib/recorder-extension-store"
import {
  RECORDER_EXTENSION_EVENT_CHANNEL,
  emitRecorderExtensionEvent,
  type RecorderExtensionEvent,
} from "@/lib/recorder-extension-telemetry"
import {
  RECORDER_BRIDGE_PONG,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
} from "../../../../packages/shared/websiteProofRecorderContract"

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}))

type SentMessage = { source?: string; type?: string; payload?: Record<string, unknown> }

/** Impersonates the extension's content-script bridge answering the ping. */
function replyToPings(pong: (requestId: string) => Record<string, unknown> | null) {
  const listener = (event: MessageEvent) => {
    const data = event.data as SentMessage
    if (data?.source !== "veribridge-app" || data.type !== "VERIBRIDGE_RECORDER_BRIDGE_PING") return
    const payload = pong(String(data.payload?.request_id ?? ""))
    if (!payload) return
    window.dispatchEvent(new MessageEvent("message", {
      source: window,
      origin: window.location.origin,
      data: { source: "veribridge-extension", type: RECORDER_BRIDGE_PONG, payload },
    }))
  }
  window.addEventListener("message", listener)
  return () => window.removeEventListener("message", listener)
}

const READY_PONG = (request_id: string) => ({
  request_id,
  schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
  build_version: "1.0.1",
  context_valid: true,
  bridge_trusted: true,
})

const CHROME_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
const ANDROID_UA =
  "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36"

function setUserAgent(ua: string) {
  Object.defineProperty(window.navigator, "userAgent", { value: ua, configurable: true })
}

beforeEach(() => {
  setUserAgent(CHROME_UA)
  vi.spyOn(console, "info").mockImplementation(() => undefined)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe("Student Dashboard — RecorderExtensionCard", () => {
  it("offers a direct install CTA to the official listing when the extension is absent", async () => {
    render(<RecorderExtensionCard />)
    const link = await screen.findByTestId("dashboard-recorder-install-link")
    expect(link.getAttribute("href")).toBe(VERIBRIDGE_CHROME_EXTENSION_URL)
    expect(link.getAttribute("target")).toBe("_blank")
    // Safe external navigation.
    expect(link.getAttribute("rel")).toBe("noopener noreferrer")
    // Accessible label, not icon-only.
    expect(link.textContent).toContain("Chrome extension")
    expect(link.getAttribute("aria-label")).toContain("opens the Chrome Web Store in a new tab")

    // The absent verdict only lands after the probe's ping deadline elapses.
    await waitFor(
      () =>
        expect(screen.getByTestId("dashboard-recorder-extension-card").dataset.recorderStatus).toBe("absent"),
      { timeout: 4_000 },
    )
    expect(screen.getByTestId("dashboard-recorder-status-chip").textContent).toBe("Not installed")
    // Post-install recovery without a full app refresh.
    expect(screen.getByTestId("dashboard-recorder-recheck")).toBeTruthy()
  })

  it("never claims installation before a probe resolves", () => {
    // First paint, probe still in flight: the copy must stay neutral so a
    // student who already has the recorder is not told to install it.
    render(<RecorderExtensionCard />)
    expect(screen.getByTestId("dashboard-recorder-status-chip").textContent).toBe("Checking…")
    expect(screen.getByTestId("dashboard-recorder-install-link").textContent).toContain(
      "Get Chrome extension",
    )
  })

  it("shows detected state and a Website Proof entry point once the bridge answers", async () => {
    const detach = replyToPings(READY_PONG)
    try {
      render(<RecorderExtensionCard />)
      await waitFor(() =>
        expect(screen.getByTestId("dashboard-recorder-extension-card").dataset.recorderStatus).toBe("detected"),
      )
      expect(screen.getByTestId("dashboard-recorder-status-chip").textContent).toContain("Recorder detected")
      expect(screen.getByTestId("dashboard-recorder-status-chip").textContent).toContain("v1.0.1")
      // An installed extension is NOT told to install.
      expect(screen.queryByTestId("dashboard-recorder-install-link")).toBeNull()
      expect(screen.getByTestId("dashboard-recorder-open-website-proof").getAttribute("href")).toBe(
        "/student/proofs/website",
      )
      // Secondary store link stays available, but only as "view".
      expect(screen.getByTestId("dashboard-recorder-store-link").getAttribute("href")).toBe(
        VERIBRIDGE_CHROME_EXTENSION_URL,
      )
    } finally {
      detach()
    }
  })

  it("flags an outdated build as an update, not a fresh install", async () => {
    const detach = replyToPings((request_id) => ({ ...READY_PONG(request_id), build_version: "0.2.1" }))
    try {
      render(<RecorderExtensionCard />)
      await waitFor(() =>
        expect(screen.getByTestId("dashboard-recorder-extension-card").dataset.recorderStatus).toBe("outdated"),
      )
      expect(screen.getByTestId("dashboard-recorder-status-chip").textContent).toBe("Update required")
      expect(screen.getByTestId("dashboard-recorder-install-link").textContent).toContain(
        "Update in Chrome Web Store",
      )
    } finally {
      detach()
    }
  })

  it("routes an orphaned bridge to a page refresh instead of the store", async () => {
    const detach = replyToPings((request_id) => ({ ...READY_PONG(request_id), context_valid: false }))
    try {
      render(<RecorderExtensionCard />)
      await waitFor(() =>
        expect(screen.getByTestId("dashboard-recorder-extension-card").dataset.recorderStatus).toBe("reload_needed"),
      )
      expect(screen.getByTestId("dashboard-recorder-refresh")).toBeTruthy()
      expect(screen.queryByTestId("dashboard-recorder-install-link")).toBeNull()
    } finally {
      detach()
    }
  })

  it("makes no readiness claim on a browser that cannot run the recorder", () => {
    setUserAgent(ANDROID_UA)
    render(<RecorderExtensionCard />)
    const card = screen.getByTestId("dashboard-recorder-extension-card")
    expect(card.dataset.recorderStatus).toBe("unsupported")
    expect(screen.getByTestId("dashboard-recorder-status-chip").textContent).toBe("Chrome required")
    expect(card.textContent).toContain("requires desktop Google Chrome")
    expect(card.textContent).not.toContain("ready to record")
    // Store listing is still viewable, but there is no "check again" affordance
    // on a browser that can never answer the bridge.
    expect(screen.getByTestId("dashboard-recorder-install-link")).toBeTruthy()
    expect(screen.queryByTestId("dashboard-recorder-recheck")).toBeNull()
  })

  it("does not treat a store click as proof of installation", async () => {
    render(<RecorderExtensionCard />)
    const link = await screen.findByTestId("dashboard-recorder-install-link")
    link.click()
    // No bridge is answering, so the card must stay in the absent state.
    await waitFor(
      () =>
        expect(screen.getByTestId("dashboard-recorder-extension-card").dataset.recorderStatus).toBe("absent"),
      { timeout: 4_000 },
    )
    expect(screen.queryByTestId("dashboard-recorder-open-website-proof")).toBeNull()
  })
})

describe("Website Proof — pre-start readiness badge", () => {
  it("stays hidden until detection is confirmed", async () => {
    vi.useFakeTimers()
    render(<RecorderReadyBadge />)
    await vi.advanceTimersByTimeAsync(2_500)
    expect(screen.queryByTestId("recorder-ready-badge")).toBeNull()
  })

  it("confirms readiness once the bridge answers", async () => {
    const detach = replyToPings(READY_PONG)
    try {
      render(<RecorderReadyBadge />)
      const badge = await screen.findByTestId("recorder-ready-badge")
      expect(badge.textContent).toContain("VeriBridge Recorder detected")
      expect(badge.textContent).toContain("ready to record")
    } finally {
      detach()
    }
  })
})

describe("recorder runtime failures are not installation failures", () => {
  it("classifies only handshake/connection diagnostics as connection failures", () => {
    expect(isRecorderConnectionFailure("WPR-EXTENSION-WORKER-UNREACHABLE")).toBe(true)
    expect(isRecorderConnectionFailure("WPR-INITIALIZATION-TIMEOUT")).toBe(true)
    expect(isRecorderConnectionFailure("WPR-STORAGE-WRITE-FAILED")).toBe(true)
    // Installation problems belong to the install gate, not here.
    expect(isRecorderConnectionFailure("WPR-EXTENSION-NOT-DETECTED")).toBe(false)
    expect(isRecorderConnectionFailure("WPR-EXTENSION-VERSION-INCOMPATIBLE")).toBe(false)
    expect(isRecorderConnectionFailure("WPR-EXTENSION-CONTEXT-INVALIDATED")).toBe(false)
    // Session/target states keep their own established recovery behavior.
    expect(isRecorderConnectionFailure("WPR-DIFFERENT-SESSION-ACTIVE")).toBe(false)
    expect(isRecorderConnectionFailure("WPR-SESSION-MISMATCH")).toBe(false)
    expect(isRecorderConnectionFailure("WPR-TARGET-READY-TIMEOUT")).toBe(false)
    expect(isRecorderConnectionFailure("WPR-REPLAY-NOT-RETAINED")).toBe(false)
    expect(isRecorderConnectionFailure(null)).toBe(false)
  })

  it("keeps different-session-active out of BOTH the install gate and the connection panel", () => {
    // Regression guard: a different active recording session must never be
    // rendered as "install the extension".
    expect(recorderGateReasonFor("WPR-DIFFERENT-SESSION-ACTIVE")).toBeNull()
    expect(isRecorderConnectionFailure("WPR-DIFFERENT-SESSION-ACTIVE")).toBe(false)
  })

  it("offers retry (not install) and preserves the diagnostic code", async () => {
    const onRetry = vi.fn()
    render(
      <RecorderConnectionRecovery
        message="The recorder's background worker did not answer. (WPR-EXTENSION-WORKER-UNREACHABLE)"
        onRetry={onRetry}
        retrying={false}
      />,
    )
    const panel = screen.getByTestId("recorder-connection-recovery")
    expect(panel.textContent).not.toContain("Install")
    expect(screen.getByTestId("recorder-connection-diagnostic").textContent).toContain(
      "WPR-EXTENSION-WORKER-UNREACHABLE",
    )
    const retry = screen.getByTestId("recorder-connection-retry")
    expect(retry.textContent).toBe("Retry connection")
    retry.click()
    expect(onRetry).toHaveBeenCalledTimes(1)
    // Secondary "view extension" affordance, safely linked.
    const storeLink = screen.getByTestId("recorder-connection-store-link")
    expect(storeLink.getAttribute("href")).toBe(VERIBRIDGE_CHROME_EXTENSION_URL)
    expect(storeLink.getAttribute("rel")).toBe("noopener noreferrer")
  })

  it("only claims the recorder is 'detected' when the bridge actually answers", async () => {
    const detach = replyToPings(READY_PONG)
    try {
      render(
        <RecorderConnectionRecovery message="WPR-INITIALIZATION-TIMEOUT" onRetry={() => undefined} retrying={false} />,
      )
      await waitFor(() =>
        expect(screen.getByTestId("recorder-connection-recovery").textContent).toContain(
          "Recorder detected, but VeriBridge couldn't connect to it",
        ),
      )
    } finally {
      detach()
    }
  })
})

describe("discovery telemetry", () => {
  it("emits non-identifying install-funnel events on the shared channel", () => {
    const received: RecorderExtensionEvent[] = []
    const listener = (event: Event) => {
      received.push((event as CustomEvent<RecorderExtensionEvent>).detail)
    }
    window.addEventListener(RECORDER_EXTENSION_EVENT_CHANNEL, listener)
    try {
      emitRecorderExtensionEvent("extension_install_clicked", "dashboard", { reason: "absent" })
      emitRecorderExtensionEvent("extension_detected_after_install", "website_proof", {
        build_version: "1.0.1",
      })
    } finally {
      window.removeEventListener(RECORDER_EXTENSION_EVENT_CHANNEL, listener)
    }
    expect(received).toEqual([
      { name: "extension_install_clicked", surface: "dashboard", detail: { reason: "absent" } },
      {
        name: "extension_detected_after_install",
        surface: "website_proof",
        detail: { build_version: "1.0.1" },
      },
    ])
    // No identity anywhere in the payloads.
    const serialized = JSON.stringify(received)
    expect(serialized).not.toMatch(/@|user_id|session_id|access_token/)
  })

  it("emits an install-click event from the dashboard card", async () => {
    const received: RecorderExtensionEvent[] = []
    const listener = (event: Event) => {
      received.push((event as CustomEvent<RecorderExtensionEvent>).detail)
    }
    window.addEventListener(RECORDER_EXTENSION_EVENT_CHANNEL, listener)
    try {
      render(<RecorderExtensionCard />)
      const link = await screen.findByTestId("dashboard-recorder-install-link")
      link.click()
    } finally {
      window.removeEventListener(RECORDER_EXTENSION_EVENT_CHANNEL, listener)
    }
    expect(received.some((e) => e.name === "extension_install_clicked" && e.surface === "dashboard")).toBe(true)
  })
})
