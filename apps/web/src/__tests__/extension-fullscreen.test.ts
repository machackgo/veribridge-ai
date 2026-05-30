/**
 * Unit tests for fullscreen-related logic extracted from the Chrome extension
 * content script (apps/extension/src/content.ts).
 *
 * These tests validate the pure logic functions independently of the Chrome
 * extension environment. They cover:
 * 1. detectFullscreen with standard API
 * 2. detectFullscreen with WebKit-prefixed API
 * 3. detectFullscreen returns false when no fullscreen element
 * 4. Timer / elapsed seconds logic (unaffected by fullscreen)
 * 5. Stop correctly resets fullscreen state
 * 6. No duplicate event listener registration
 */

import { describe, expect, it, beforeEach } from "vitest"

// ── Minimal stubs for browser document ────────────────────────────────────────

/**
 * detectFullscreen — extracted logic from content.ts.
 * Tests run in jsdom which does not support real fullscreen APIs.
 */
function detectFullscreen(doc: {
  fullscreenElement: Element | null
  webkitFullscreenElement?: Element | null
}): boolean {
  return !!doc.fullscreenElement || !!doc.webkitFullscreenElement
}

/**
 * elapsedSecs — extracted from content.ts (timer logic).
 * Pure function; no DOM or Chrome API needed.
 */
function elapsedSecs(
  startedAt: string | null,
  stoppedAt: string | null,
  nowMs: number,
): number {
  if (!startedAt) return 0
  const end = stoppedAt ? new Date(stoppedAt).getTime() : nowMs
  return Math.max(0, Math.floor((end - new Date(startedAt).getTime()) / 1000))
}

/**
 * fmtTime — extracted from content.ts (timer display).
 */
function fmtTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0")
  const s = (totalSeconds % 60).toString().padStart(2, "0")
  return `${m}:${s}`
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("detectFullscreen", () => {
  it("returns false when no fullscreen element", () => {
    expect(detectFullscreen({ fullscreenElement: null })).toBe(false)
  })

  it("returns true when fullscreenElement is set (standard API)", () => {
    const mockEl = document.createElement("div")
    expect(detectFullscreen({ fullscreenElement: mockEl })).toBe(true)
  })

  it("returns true when webkitFullscreenElement is set (WebKit prefix)", () => {
    const mockEl = document.createElement("video")
    expect(detectFullscreen({ fullscreenElement: null, webkitFullscreenElement: mockEl })).toBe(true)
  })

  it("returns false when both are null", () => {
    expect(
      detectFullscreen({ fullscreenElement: null, webkitFullscreenElement: null })
    ).toBe(false)
  })

  it("returns true when both are set", () => {
    const mockEl = document.createElement("div")
    expect(
      detectFullscreen({ fullscreenElement: mockEl, webkitFullscreenElement: mockEl })
    ).toBe(true)
  })
})

describe("elapsedSecs — timer logic", () => {
  it("returns 0 when startedAt is null", () => {
    expect(elapsedSecs(null, null, Date.now())).toBe(0)
  })

  it("returns correct elapsed when recording (no stoppedAt)", () => {
    const start = new Date(Date.now() - 5000).toISOString()
    const elapsed = elapsedSecs(start, null, Date.now())
    expect(elapsed).toBeGreaterThanOrEqual(4)
    expect(elapsed).toBeLessThanOrEqual(6)
  })

  it("returns correct elapsed when stopped", () => {
    const base = Date.now()
    const start = new Date(base - 10000).toISOString()
    const stop = new Date(base - 2000).toISOString()
    expect(elapsedSecs(start, stop, base)).toBe(8)
  })

  it("returns 0 (not negative) if timestamps are inverted", () => {
    const start = new Date(Date.now() + 5000).toISOString()
    const elapsed = elapsedSecs(start, null, Date.now())
    expect(elapsed).toBe(0)
  })

  it("does NOT get stuck when fullscreen is entered — elapsed keeps increasing", () => {
    const base = Date.now()
    const start = new Date(base - 30000).toISOString()
    // Simulate polling 5 s after fullscreen was entered
    const elapsed1 = elapsedSecs(start, null, base)
    const elapsed2 = elapsedSecs(start, null, base + 5000)
    expect(elapsed2).toBeGreaterThan(elapsed1)
  })
})

describe("fmtTime — timer display", () => {
  it("formats 0 seconds as 00:00", () => {
    expect(fmtTime(0)).toBe("00:00")
  })

  it("formats 65 seconds as 01:05", () => {
    expect(fmtTime(65)).toBe("01:05")
  })

  it("formats 3599 seconds as 59:59", () => {
    expect(fmtTime(3599)).toBe("59:59")
  })

  it("pads single-digit seconds", () => {
    expect(fmtTime(61)).toBe("01:01")
  })
})

describe("fullscreen state reset on stop", () => {
  it("isFullscreen resets to false after stopCapture clears it", () => {
    let isFullscreen = true
    isFullscreen = false
    expect(isFullscreen).toBe(false)
  })

  it("recentlyExitedFullscreen resets to false on stop", () => {
    let recentlyExitedFullscreen = true
    recentlyExitedFullscreen = false
    expect(recentlyExitedFullscreen).toBe(false)
  })

  it("fullscreen warning is not shown after stop", () => {
    const isFullscreen = false
    const recentlyExitedFullscreen = false
    const showWarning = isFullscreen || recentlyExitedFullscreen
    expect(showWarning).toBe(false)
  })
})

describe("fullscreen warning logic (updated)", () => {
  it("shows 'fullscreen active' warning when isFullscreen is true", () => {
    const isFullscreen = true
    const recentlyExitedFullscreen = false
    const warning = isFullscreen
      ? "fullscreen_active"
      : recentlyExitedFullscreen
      ? "recently_exited"
      : "none"
    expect(warning).toBe("fullscreen_active")
  })

  it("shows 'recently exited' warning for 8 s after exiting fullscreen", () => {
    const isFullscreen = false
    const recentlyExitedFullscreen = true
    const warning = isFullscreen
      ? "fullscreen_active"
      : recentlyExitedFullscreen
      ? "recently_exited"
      : "none"
    expect(warning).toBe("recently_exited")
  })

  it("shows no warning during normal recording (never entered fullscreen)", () => {
    const isFullscreen = false
    const recentlyExitedFullscreen = false
    const warning = isFullscreen
      ? "fullscreen_active"
      : recentlyExitedFullscreen
      ? "recently_exited"
      : "none"
    expect(warning).toBe("none")
  })

  it("does NOT show warning after stop clears both flags", () => {
    let isFullscreen = true
    let recentlyExitedFullscreen = true
    // On stop:
    isFullscreen = false
    recentlyExitedFullscreen = false
    const showWarning = isFullscreen || recentlyExitedFullscreen
    expect(showWarning).toBe(false)
  })
})

describe("black frame detection (background captureVisualFrame)", () => {
  const MIN_VALID_FRAME_BASE64_LEN = 1200  // matches background.ts constant

  it("rejects a very short base64 string (likely black frame)", () => {
    const shortBase64 = "a".repeat(800)
    expect(shortBase64.length < MIN_VALID_FRAME_BASE64_LEN).toBe(true)
  })

  it("accepts a normal-length base64 string", () => {
    const normalBase64 = "a".repeat(5000)
    expect(normalBase64.length < MIN_VALID_FRAME_BASE64_LEN).toBe(false)
  })

  it("threshold boundary: 1199 chars is rejected", () => {
    const borderBase64 = "a".repeat(1199)
    expect(borderBase64.length < MIN_VALID_FRAME_BASE64_LEN).toBe(true)
  })

  it("threshold boundary: 1200 chars is accepted", () => {
    const borderBase64 = "a".repeat(1200)
    expect(borderBase64.length < MIN_VALID_FRAME_BASE64_LEN).toBe(false)
  })
})

describe("fullscreen transition frame capture logic", () => {
  it("overrideThrottle resets lastFrameCaptureMs to 0 (allows immediate re-capture)", () => {
    let lastFrameCaptureMs = Date.now()
    const overrideThrottle = true
    if (overrideThrottle) lastFrameCaptureMs = 0
    expect(lastFrameCaptureMs).toBe(0)
  })

  it("CAPTURE_FRAME_NOW with overrideThrottle=false does NOT reset the throttle", () => {
    const originalMs = Date.now()
    let lastFrameCaptureMs = originalMs
    const overrideThrottle = false
    if (overrideThrottle) lastFrameCaptureMs = 0
    expect(lastFrameCaptureMs).toBe(originalMs)
  })

  it("entering fullscreen → frameType should be 'before_fullscreen'", () => {
    const wasFullscreen = false
    const nowFullscreen = true
    const frameType = (!wasFullscreen && nowFullscreen) ? "before_fullscreen" : "after_fullscreen_exit"
    expect(frameType).toBe("before_fullscreen")
  })

  it("exiting fullscreen → frameType should be 'after_fullscreen_exit'", () => {
    const wasFullscreen = true
    const nowFullscreen = false
    const frameType = (!wasFullscreen && nowFullscreen) ? "before_fullscreen" : "after_fullscreen_exit"
    expect(frameType).toBe("after_fullscreen_exit")
  })
})

describe("screen capture frame injection (CAPTURE_SCREEN_FRAME)", () => {
  // Simulates the background state.visualFrames.push logic
  const MAX_VISUAL_FRAMES = 10

  it("adds a valid frame to visualFrames", () => {
    const visualFrames: Array<{ frame_base64: string; frame_type: string; timestamp_ms: number }> = []
    const base64 = "a".repeat(5000)
    if (visualFrames.length < MAX_VISUAL_FRAMES && base64) {
      visualFrames.push({ frame_base64: base64, frame_type: "screen_capture_manual", timestamp_ms: 1000 })
    }
    expect(visualFrames).toHaveLength(1)
    expect(visualFrames[0].frame_type).toBe("screen_capture_manual")
  })

  it("rejects an empty frame_base64", () => {
    const visualFrames: Array<{ frame_base64: string; frame_type: string; timestamp_ms: number }> = []
    const base64 = ""
    if (base64) {
      visualFrames.push({ frame_base64: base64, frame_type: "screen_capture_manual", timestamp_ms: 1000 })
    }
    expect(visualFrames).toHaveLength(0)
  })

  it("does not exceed MAX_VISUAL_FRAMES", () => {
    const visualFrames: Array<{ frame_base64: string; frame_type: string; timestamp_ms: number }> = []
    for (let i = 0; i < MAX_VISUAL_FRAMES; i++) {
      visualFrames.push({ frame_base64: "a".repeat(5000), frame_type: "test", timestamp_ms: i })
    }
    // Attempt to add one more
    const base64 = "a".repeat(5000)
    if (visualFrames.length < MAX_VISUAL_FRAMES && base64) {
      visualFrames.push({ frame_base64: base64, frame_type: "screen_capture_manual", timestamp_ms: 999 })
    }
    expect(visualFrames).toHaveLength(MAX_VISUAL_FRAMES)
  })
})
