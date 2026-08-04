// Install-gate + detection-probe coverage for the Chrome Web Store flow:
// missing-extension prompt, installed detection, outdated build, spoofed
// messages, and the no-listing-yet safe state.

import { describe, expect, it, vi, afterEach } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import React from "react"

import {
  probeRecorderExtension,
} from "@/lib/website-proof-recorder"
import {
  detectRecorderBrowserSupport,
  isRecorderStoreListingLive,
} from "@/lib/recorder-extension-store"
import {
  RecorderInstallGate,
  recorderGateReasonFor,
} from "../../components/skill-proof/recorder-install-gate"
import {
  RECORDER_BRIDGE_PONG,
  WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
} from "../../../../packages/shared/websiteProofRecorderContract"

type SentMessage = { source?: string; type?: string; payload?: Record<string, unknown> }

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

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("probeRecorderExtension", () => {
  it("reports absent when nothing answers", async () => {
    vi.useFakeTimers()
    const pending = probeRecorderExtension()
    await vi.advanceTimersByTimeAsync(2_200)
    await expect(pending).resolves.toMatchObject({ installed: false, ready: false })
  })

  it("reports ready for a compatible installed build", async () => {
    const detach = replyToPings((request_id) => ({
      request_id,
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "1.0.0",
      context_valid: true,
      bridge_trusted: true,
    }))
    try {
      await expect(probeRecorderExtension()).resolves.toMatchObject({
        installed: true,
        ready: true,
        outdated: false,
        build_version: "1.0.0",
      })
    } finally {
      detach()
    }
  })

  it("reports outdated for an old build", async () => {
    const detach = replyToPings((request_id) => ({
      request_id,
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "0.2.1",
      context_valid: true,
      bridge_trusted: true,
    }))
    try {
      await expect(probeRecorderExtension()).resolves.toMatchObject({
        installed: true,
        ready: false,
        outdated: true,
      })
    } finally {
      detach()
    }
  })

  it("reports a reload-needed (orphaned) bridge as not ready", async () => {
    const detach = replyToPings((request_id) => ({
      request_id,
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "1.0.0",
      context_valid: false,
      bridge_trusted: true,
    }))
    try {
      await expect(probeRecorderExtension()).resolves.toMatchObject({
        installed: true,
        ready: false,
        context_valid: false,
      })
    } finally {
      detach()
    }
  })

  it("ignores a spoofed pong with the wrong correlation id", async () => {
    vi.useFakeTimers()
    const detach = replyToPings(() => ({
      request_id: "spoofed-correlation",
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "1.0.0",
      context_valid: true,
      bridge_trusted: true,
    }))
    try {
      const pending = probeRecorderExtension()
      await vi.advanceTimersByTimeAsync(2_200)
      await expect(pending).resolves.toMatchObject({ installed: false })
    } finally {
      detach()
    }
  })
})

describe("recorderGateReasonFor", () => {
  it("maps only extension-availability diagnostics to a gate reason", () => {
    expect(recorderGateReasonFor("WPR-EXTENSION-NOT-DETECTED")).toBe("not_installed")
    expect(recorderGateReasonFor("WPR-EXTENSION-VERSION-INCOMPATIBLE")).toBe("outdated")
    expect(recorderGateReasonFor("WPR-EXTENSION-CONTEXT-INVALIDATED")).toBe("reload_needed")
    expect(recorderGateReasonFor("WPR-SESSION-MISMATCH")).toBeNull()
    expect(recorderGateReasonFor("WPR-EXTENSION-WORKER-UNREACHABLE")).toBeNull()
    expect(recorderGateReasonFor(null)).toBeNull()
  })
})

describe("recorder-extension-store helpers", () => {
  it("treats only real Chrome Web Store URLs as a live listing", () => {
    // Env-driven URL is empty in tests → not live.
    expect(isRecorderStoreListingLive()).toBe(false)
  })

  it("classifies browser support from the user agent", () => {
    const chrome =
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    const edge = chrome + " Edg/150.0.0.0"
    const firefox = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:150.0) Gecko/20100101 Firefox/150.0"
    const safari =
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
    const androidChrome =
      "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36"
    expect(detectRecorderBrowserSupport(chrome)).toBe("supported")
    expect(detectRecorderBrowserSupport(edge)).toBe("supported")
    expect(detectRecorderBrowserSupport(firefox)).toBe("unsupported")
    expect(detectRecorderBrowserSupport(safari)).toBe("unsupported")
    expect(detectRecorderBrowserSupport(androidChrome)).toBe("unsupported")
  })
})

describe("RecorderInstallGate", () => {
  it("shows the pending-release state (no broken store link) when no listing URL is configured", async () => {
    render(
      <RecorderInstallGate reason="not_installed" onContinue={() => undefined} continuing={false} />,
    )
    expect(await screen.findByTestId("recorder-gate-pending-release")).toBeTruthy()
    expect(screen.queryByTestId("recorder-gate-install-link")).toBeNull()
    expect(screen.getByTestId("recorder-gate-recheck")).toBeTruthy()
  })

  it("offers continue once the extension is detected as ready", async () => {
    const detach = replyToPings((request_id) => ({
      request_id,
      schema_version: WEBSITE_PROOF_RECORDER_SCHEMA_VERSION,
      build_version: "1.0.0",
      context_valid: true,
      bridge_trusted: true,
    }))
    try {
      render(
        <RecorderInstallGate reason="not_installed" onContinue={() => undefined} continuing={false} />,
      )
      expect(await screen.findByTestId("recorder-detected-banner")).toBeTruthy()
      expect(screen.getByTestId("recorder-gate-continue")).toBeTruthy()
    } finally {
      detach()
    }
  })
})
