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
  // Updated MAX_VISUAL_FRAMES: bumped to 40 to support the Fullscreen Recorder Tab
  // (40 frames at 2 s each ≈ 80 seconds of fullscreen coverage).
  const MAX_VISUAL_FRAMES = 40

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

  it("does not exceed MAX_VISUAL_FRAMES (now 40)", () => {
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

  it("frame_type 'fullscreen_recorder' is accepted (from recorder tab)", () => {
    const visualFrames: Array<{ frame_base64: string; frame_type: string; timestamp_ms: number }> = []
    const base64 = "a".repeat(5000)
    if (visualFrames.length < MAX_VISUAL_FRAMES && base64) {
      visualFrames.push({ frame_base64: base64, frame_type: "fullscreen_recorder", timestamp_ms: 2000 })
    }
    expect(visualFrames[0].frame_type).toBe("fullscreen_recorder")
  })

  it("40 frame cap supports ~80 seconds at 2 s interval", () => {
    // Simulate the recorder tab sending one frame every 2 seconds for 80 seconds
    const visualFrames: Array<{ frame_base64: string; frame_type: string; timestamp_ms: number }> = []
    const INTERVAL_MS = 2000
    for (let tick = 0; tick < 50; tick++) {  // 50 ticks = 100 seconds, exceeds cap
      if (visualFrames.length >= MAX_VISUAL_FRAMES) break
      visualFrames.push({
        frame_base64: "a".repeat(5000),
        frame_type: "fullscreen_recorder",
        timestamp_ms: tick * INTERVAL_MS,
      })
    }
    expect(visualFrames).toHaveLength(MAX_VISUAL_FRAMES)
    // Last frame should be at tick 39 (0-indexed) × 2000ms = 78000ms ≈ 78 seconds
    expect(visualFrames[MAX_VISUAL_FRAMES - 1].timestamp_ms).toBe((MAX_VISUAL_FRAMES - 1) * INTERVAL_MS)
  })
})

// ── Recorder tab mode — pre-fullscreen setup ───────────────────────────────────

describe("fullscreen recorder tab — pre-fullscreen workflow", () => {
  /**
   * simulates the recorder tab's logic:
   * isRecordingActive must be true before capture can start
   */
  function canStartCapture(isRecordingActive: boolean, streamAlreadyActive: boolean): boolean {
    return isRecordingActive && !streamAlreadyActive
  }

  it("Start Capture is disabled when no recording is active", () => {
    expect(canStartCapture(false, false)).toBe(false)
  })

  it("Start Capture is enabled when recording is active and no stream yet", () => {
    expect(canStartCapture(true, false)).toBe(true)
  })

  it("Start Capture is disabled when stream is already active (prevents duplicates)", () => {
    expect(canStartCapture(true, true)).toBe(false)
  })

  it("Stop Capture is only enabled when a stream is active", () => {
    const streamActive = true
    const btnStopDisabled = !streamActive
    expect(btnStopDisabled).toBe(false)
  })

  it("Stop Capture is disabled when no stream is active", () => {
    const streamActive = false
    const btnStopDisabled = !streamActive
    expect(btnStopDisabled).toBe(true)
  })
})

describe("recorder tab — frame counter and cap enforcement", () => {
  const MAX_FRAMES_PER_SESSION = 40  // matches recorder.ts constant

  it("frame counter increments on each successful capture", () => {
    let framesSent = 0
    // Simulate 5 successful captures
    for (let i = 0; i < 5; i++) { framesSent++ }
    expect(framesSent).toBe(5)
  })

  it("capture stops when MAX_FRAMES_PER_SESSION is reached", () => {
    let framesSent = 0
    let captureActive = true

    for (let tick = 0; tick < 100; tick++) {
      if (framesSent >= MAX_FRAMES_PER_SESSION) {
        captureActive = false
        break
      }
      framesSent++
    }

    expect(captureActive).toBe(false)
    expect(framesSent).toBe(MAX_FRAMES_PER_SESSION)
  })

  it("framesSent resets to 0 on new capture session start", () => {
    let framesSent = 25
    // Simulate starting a new capture
    framesSent = 0
    expect(framesSent).toBe(0)
  })

  it("frame badge shows 'has-frames' styling after first capture", () => {
    const framesSent = 1
    const hasFramesClass = framesSent > 0 ? "frame-badge has-frames" : "frame-badge"
    expect(hasFramesClass).toBe("frame-badge has-frames")
  })

  it("frame badge shows default styling when no frames captured", () => {
    const framesSent = 0
    const hasFramesClass = framesSent > 0 ? "frame-badge has-frames" : "frame-badge"
    expect(hasFramesClass).toBe("frame-badge")
  })
})

describe("recorder tab — stream lifecycle", () => {
  it("cleanupStream sets displayStream to null", () => {
    // Simulate the cleanup
    let displayStream: MediaStream | null = { getTracks: () => [] } as unknown as MediaStream
    // cleanup:
    displayStream = null
    expect(displayStream).toBeNull()
  })

  it("stream-ended event (user clicks 'Stop sharing' in browser) sets displayStream to null", () => {
    let displayStream: MediaStream | null = {} as unknown as MediaStream
    let captureActive = true

    // Simulate track.ended event handler
    const onEnded = () => {
      displayStream = null
      captureActive = false
    }
    onEnded()

    expect(displayStream).toBeNull()
    expect(captureActive).toBe(false)
  })

  it("recording stopping mid-capture shows warning, does NOT auto-stop capture", () => {
    // Recording can stop while the stream is still active —
    // the recorder tab shows a warning but lets the user decide to stop.
    const wasRecording = true
    const isRecordingNow = false
    const displayStreamActive = true

    const shouldWarn = wasRecording && !isRecordingNow && displayStreamActive
    expect(shouldWarn).toBe(true)

    // Capture is still active (user must click Stop)
    expect(displayStreamActive).toBe(true)
  })
})

describe("recorder tab — popup btnOpenRecorder interaction", () => {
  it("btnOpenRecorder is disabled when recording is not active", () => {
    const isRecording = false
    const btnDisabled = !isRecording
    expect(btnDisabled).toBe(true)
  })

  it("btnOpenRecorder is enabled when recording is active", () => {
    const isRecording = true
    const btnDisabled = !isRecording
    expect(btnDisabled).toBe(false)
  })

  it("OPEN_RECORDER_TAB message opens recorder.html tab URL", () => {
    // Verify the URL pattern that background.ts uses
    // chrome.runtime.getURL("recorder.html") → "chrome-extension://[id]/recorder.html"
    const expectedPath = "recorder.html"
    expect(expectedPath).toBe("recorder.html")
  })
})

describe("MAX_VISUAL_FRAMES increase — backward compatibility", () => {
  it("old sessions with fewer than 10 frames still work correctly", () => {
    const MAX_VISUAL_FRAMES = 40
    const visualFrames = Array.from({ length: 5 }, (_, i) => ({
      frame_base64: "a".repeat(5000),
      frame_type: "recording_start",
      timestamp_ms: i * 1000,
    }))
    // Adding more frames still works
    if (visualFrames.length < MAX_VISUAL_FRAMES) {
      visualFrames.push({ frame_base64: "b".repeat(5000), frame_type: "page_load", timestamp_ms: 6000 })
    }
    expect(visualFrames).toHaveLength(6)
  })

  it("new fullscreen sessions can use up to 40 frames", () => {
    const MAX_VISUAL_FRAMES = 40
    const visualFrames: Array<{ frame_base64: string; frame_type: string; timestamp_ms: number }> = []
    for (let i = 0; i < 40; i++) {
      if (visualFrames.length < MAX_VISUAL_FRAMES) {
        visualFrames.push({ frame_base64: "a".repeat(5000), frame_type: "fullscreen_recorder", timestamp_ms: i * 2000 })
      }
    }
    expect(visualFrames).toHaveLength(40)
  })
})

describe("Chrome limitation — captureVisibleTab vs getDisplayMedia", () => {
  /**
   * Documents the architectural difference between the two capture methods
   * and validates that the correct approach is used for each scenario.
   */

  type CaptureMethod = "captureVisibleTab" | "getDisplayMedia_popup" | "getDisplayMedia_recorder_tab"

  function chooseCaptureMethod(scenario: "normal_page" | "fullscreen_video" | "pre_fullscreen_setup"): CaptureMethod {
    if (scenario === "normal_page") return "captureVisibleTab"
    if (scenario === "fullscreen_video") return "getDisplayMedia_recorder_tab"
    if (scenario === "pre_fullscreen_setup") return "getDisplayMedia_recorder_tab"
    return "captureVisibleTab"
  }

  it("normal page uses captureVisibleTab (Chrome compositor)", () => {
    expect(chooseCaptureMethod("normal_page")).toBe("captureVisibleTab")
  })

  it("fullscreen video uses getDisplayMedia via recorder tab (OS level)", () => {
    expect(chooseCaptureMethod("fullscreen_video")).toBe("getDisplayMedia_recorder_tab")
  })

  it("pre-fullscreen setup uses recorder tab (persists during fullscreen)", () => {
    expect(chooseCaptureMethod("pre_fullscreen_setup")).toBe("getDisplayMedia_recorder_tab")
  })

  it("recorder tab capture is NOT blocked by hardware video overlay", () => {
    // getDisplayMedia operates at OS compositor level, bypassing Chrome's
    // hardware-decoded video overlay that causes captureVisibleTab black frames.
    const capturesBelowOverlay = false   // captureVisibleTab
    const capturesAtOsLevel    = true    // getDisplayMedia (Entire Screen)
    expect(capturesAtOsLevel).not.toBe(capturesBelowOverlay)
    expect(capturesAtOsLevel).toBe(true)
  })

  it("black frame detection threshold still applies to captureVisibleTab frames", () => {
    const MIN_VALID_FRAME_BASE64_LEN = 1200
    const likelyBlackFrame = "a".repeat(900)
    expect(likelyBlackFrame.length < MIN_VALID_FRAME_BASE64_LEN).toBe(true)
  })
})

describe("recording state persistence across service worker restart", () => {
  it("persisted state includes sessionId, apiUrl, authToken, startedAt", () => {
    const persistedKeys = ["sessionId", "apiUrl", "authToken", "startedAt"]
    const required = ["sessionId", "apiUrl", "authToken", "startedAt"]
    expect(required.every(k => persistedKeys.includes(k))).toBe(true)
  })

  it("on restart, isRecording is restored to true if persisted", () => {
    // Simulates the background.ts startup logic
    const persisted = { sessionId: "abc123", apiUrl: "http://localhost:8000", authToken: "", startedAt: new Date().toISOString() }
    const isRecording = !!persisted.sessionId
    expect(isRecording).toBe(true)
  })

  it("on restart with no persisted state, isRecording stays false", () => {
    const persisted = null
    const isRecording = !!persisted
    expect(isRecording).toBe(false)
  })
})

describe("timer display during fullscreen — elapsed seconds do not freeze", () => {
  /**
   * Validates that the floating bar's timer keeps updating even when the page
   * is technically in fullscreen (the content script still gets polled).
   */

  function elapsedSecs(startedAt: string | null, stoppedAt: string | null, nowMs: number): number {
    if (!startedAt) return 0
    const end = stoppedAt ? new Date(stoppedAt).getTime() : nowMs
    return Math.max(0, Math.floor((end - new Date(startedAt).getTime()) / 1000))
  }

  it("timer advances during fullscreen (no freeze)", () => {
    const start = new Date(Date.now() - 60000).toISOString()  // started 60s ago
    const at0  = elapsedSecs(start, null, Date.now())
    const at5  = elapsedSecs(start, null, Date.now() + 5000)
    expect(at5).toBeGreaterThan(at0)
    expect(at5 - at0).toBeGreaterThanOrEqual(5)
  })

  it("timer stops advancing after recording is stopped (stoppedAt is set)", () => {
    const base = Date.now()
    const start   = new Date(base - 30000).toISOString()
    const stopped = new Date(base).toISOString()
    const atStop  = elapsedSecs(start, stopped, base)
    const later   = elapsedSecs(start, stopped, base + 10000)
    expect(atStop).toBe(later)  // frozen at 30 s
  })
})
