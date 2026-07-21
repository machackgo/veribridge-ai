/**
 * ReportScanner — camera lifecycle + payload validation tests.
 *
 * The camera and the native BarcodeDetector are mocked at the platform
 * boundary; everything else is the real component. The load-bearing claims:
 * the camera stops on success/close/unmount, permission problems produce
 * guidance (never a crash), unsupported browsers degrade to the paste flow,
 * and only VeriBridge report payloads are ever accepted.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ReportScanner } from "../../components/recruiter/ReportScanner"

const TOKEN = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
const CANONICAL_URL = `http://localhost:3000/vbr/report/${TOKEN}`

let trackStop: ReturnType<typeof vi.fn>
let getUserMedia: ReturnType<typeof vi.fn>
let detect: ReturnType<typeof vi.fn>

function fakeStream() {
  return { getTracks: () => [{ stop: trackStop }] } as unknown as MediaStream
}

function installCamera() {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  })
}

function installDetector() {
  class FakeBarcodeDetector {
    detect = detect
  }
  ;(window as unknown as { BarcodeDetector?: unknown }).BarcodeDetector = FakeBarcodeDetector
}

beforeEach(() => {
  trackStop = vi.fn()
  getUserMedia = vi.fn().mockResolvedValue(fakeStream())
  detect = vi.fn().mockResolvedValue([])
  installCamera()
  installDetector()
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve())
})

afterEach(() => {
  vi.restoreAllMocks()
  delete (window as unknown as { BarcodeDetector?: unknown }).BarcodeDetector
})

describe("ReportScanner", () => {
  it("starts the camera, accepts a valid report QR, stops the camera, and reports the parse", async () => {
    detect.mockResolvedValue([{ rawValue: CANONICAL_URL }])
    const onResult = vi.fn()
    render(<ReportScanner onResult={onResult} onClose={() => {}} />)

    await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1))
    expect(onResult).toHaveBeenCalledWith(
      expect.objectContaining({ ok: true, token: TOKEN, path: `/vbr/report/${TOKEN}` }),
    )
    expect(trackStop).toHaveBeenCalled()
    expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "success")
  })

  it("accepts a raw-token QR payload too", async () => {
    detect.mockResolvedValue([{ rawValue: TOKEN }])
    const onResult = vi.fn()
    render(<ReportScanner onResult={onResult} onClose={() => {}} />)
    await waitFor(() => expect(onResult).toHaveBeenCalled())
    expect(onResult.mock.calls[0][0].token).toBe(TOKEN)
  })

  it("rejects non-VeriBridge QR payloads and keeps scanning with a visible note", async () => {
    detect.mockResolvedValue([{ rawValue: "https://evil.example.com/vbr/report/" + TOKEN }])
    const onResult = vi.fn()
    render(<ReportScanner onResult={onResult} onClose={() => {}} />)

    await waitFor(() =>
      expect(screen.getByTestId("report-scanner-status").textContent).toContain(
        "not a VeriBridge report link",
      ),
    )
    expect(onResult).not.toHaveBeenCalled()
    expect(trackStop).not.toHaveBeenCalled() // still scanning
    expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "scanning")
  })

  it("scans once and never fires twice even if more frames decode", async () => {
    detect.mockResolvedValue([{ rawValue: CANONICAL_URL }, { rawValue: CANONICAL_URL }])
    const onResult = vi.fn()
    render(<ReportScanner onResult={onResult} onClose={() => {}} />)
    await waitFor(() => expect(onResult).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 800))
    expect(onResult).toHaveBeenCalledTimes(1)
  })

  it("stops the camera when closed manually", async () => {
    const onClose = vi.fn()
    render(<ReportScanner onResult={() => {}} onClose={onClose} />)
    await waitFor(() =>
      expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "scanning"),
    )
    fireEvent.click(screen.getByTestId("report-scanner-close"))
    expect(trackStop).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it("stops the camera on unmount", async () => {
    const { unmount } = render(<ReportScanner onResult={() => {}} onClose={() => {}} />)
    await waitFor(() =>
      expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "scanning"),
    )
    unmount()
    expect(trackStop).toHaveBeenCalled()
  })

  it("shows permission-denied guidance pointing at the paste fallback", async () => {
    getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"))
    render(<ReportScanner onResult={() => {}} onClose={() => {}} />)
    await waitFor(() =>
      expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "denied"),
    )
    expect(screen.getByTestId("report-scanner-status").textContent).toMatch(/paste the report link/i)
  })

  it("handles a device with no camera", async () => {
    getUserMedia.mockRejectedValue(new DOMException("none", "NotFoundError"))
    render(<ReportScanner onResult={() => {}} onClose={() => {}} />)
    await waitFor(() =>
      expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "no_camera"),
    )
  })

  it("degrades gracefully when BarcodeDetector is unavailable", async () => {
    delete (window as unknown as { BarcodeDetector?: unknown }).BarcodeDetector
    render(<ReportScanner onResult={() => {}} onClose={() => {}} />)
    expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "unsupported")
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(screen.getByTestId("report-scanner-status").textContent).toMatch(/paste the report link/i)
  })

  it("exposes an aria-live status region and an accessible camera description", async () => {
    render(<ReportScanner onResult={() => {}} onClose={() => {}} />)
    const status = screen.getByTestId("report-scanner-status")
    expect(status).toHaveAttribute("aria-live", "polite")
    expect(status).toHaveAttribute("role", "status")
    await waitFor(() =>
      expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "scanning"),
    )
    expect(screen.getByTestId("report-scanner-video").getAttribute("aria-label")).toMatch(
      /never.*(recorded|uploaded)|no video is recorded/i,
    )
  })
})
