/**
 * Recruiter open/scan page — paste flow, rejection handling, scanner
 * hand-off, source attribution, CTA, and accessibility.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn() }),
}))

import RecruiterOpenPage from "../app/recruiters/open/page"

const TOKEN = "aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
const APP = "http://localhost:3000"

function paste(value: string) {
  fireEvent.change(screen.getByTestId("recruiter-open-input"), { target: { value } })
  fireEvent.click(screen.getByTestId("recruiter-open-submit"))
}

beforeEach(() => {
  push.mockReset()
  window.sessionStorage.clear()
})

afterEach(() => {
  delete (window as unknown as { BarcodeDetector?: unknown }).BarcodeDetector
})

describe("RecruiterOpenPage — paste flow", () => {
  it("opens a report from a full public URL and tags the recruiter_open source", () => {
    render(<RecruiterOpenPage />)
    paste(`${APP}/vbr/report/${TOKEN}`)
    expect(push).toHaveBeenCalledWith(`/vbr/report/${TOKEN}`)
    expect(window.sessionStorage.getItem("vb-report-open-source")).toBe("recruiter_open")
  })

  it("opens a report from a raw public token", () => {
    render(<RecruiterOpenPage />)
    paste(TOKEN)
    expect(push).toHaveBeenCalledWith(`/vbr/report/${TOKEN}`)
  })

  it("rejects an invalid token with a visible alert and does not navigate", () => {
    render(<RecruiterOpenPage />)
    paste("definitely not a token")
    expect(push).not.toHaveBeenCalled()
    expect(screen.getByRole("alert").textContent).toMatch(/not a valid report link/i)
  })

  it("rejects arbitrary external URLs", () => {
    render(<RecruiterOpenPage />)
    paste("https://evil.example.com/careers")
    expect(push).not.toHaveBeenCalled()
    expect(screen.getByTestId("recruiter-open-error").textContent).toMatch(
      /does not point to this VeriBridge app/i,
    )
  })

  it("rejects open-redirect style report URLs on foreign origins", () => {
    render(<RecruiterOpenPage />)
    paste(`https://evil.example.com/vbr/report/${TOKEN}`)
    expect(push).not.toHaveBeenCalled()
  })

  it("rejects javascript: URLs", () => {
    render(<RecruiterOpenPage />)
    paste("javascript:alert(1)")
    expect(push).not.toHaveBeenCalled()
    expect(screen.getByTestId("recruiter-open-error").textContent).toMatch(/unsupported/i)
  })

  it("rejects oversized input", () => {
    render(<RecruiterOpenPage />)
    paste("a".repeat(4000))
    expect(push).not.toHaveBeenCalled()
    expect(screen.getByTestId("recruiter-open-error").textContent).toMatch(/too long/i)
  })

  it("clears the error once the recruiter edits the input again", () => {
    render(<RecruiterOpenPage />)
    paste("bad input")
    expect(screen.getByTestId("recruiter-open-error")).toBeInTheDocument()
    fireEvent.change(screen.getByTestId("recruiter-open-input"), { target: { value: TOKEN } })
    expect(screen.queryByTestId("recruiter-open-error")).not.toBeInTheDocument()
  })

  it("submits via the form (Enter key path) with a labelled input", () => {
    render(<RecruiterOpenPage />)
    const input = screen.getByLabelText(/report link or public token/i)
    fireEvent.change(input, { target: { value: TOKEN } })
    fireEvent.submit(screen.getByTestId("recruiter-open-form"))
    expect(push).toHaveBeenCalledWith(`/vbr/report/${TOKEN}`)
  })
})

describe("RecruiterOpenPage — scanner integration", () => {
  it("mounts the scanner only after explicit user action", () => {
    render(<RecruiterOpenPage />)
    expect(screen.queryByTestId("report-scanner")).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId("recruiter-open-scan-button"))
    expect(screen.getByTestId("report-scanner")).toBeInTheDocument()
  })

  it("falls back gracefully (paste keeps working) when scanning is unsupported", () => {
    render(<RecruiterOpenPage />)
    fireEvent.click(screen.getByTestId("recruiter-open-scan-button"))
    expect(screen.getByTestId("report-scanner")).toHaveAttribute("data-phase", "unsupported")
    paste(TOKEN)
    expect(push).toHaveBeenCalledWith(`/vbr/report/${TOKEN}`)
  })

  it("navigates with recruiter_scan attribution when the scanner finds a report QR", async () => {
    let trackStopped = false
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: () => (trackStopped = true) }],
        }),
      },
    })
    class FakeBarcodeDetector {
      detect = vi.fn().mockResolvedValue([{ rawValue: `${APP}/vbr/report/${TOKEN}` }])
    }
    ;(window as unknown as { BarcodeDetector?: unknown }).BarcodeDetector = FakeBarcodeDetector
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve())

    render(<RecruiterOpenPage />)
    fireEvent.click(screen.getByTestId("recruiter-open-scan-button"))

    await waitFor(() => expect(push).toHaveBeenCalledWith(`/vbr/report/${TOKEN}`))
    expect(window.sessionStorage.getItem("vb-report-open-source")).toBe("recruiter_scan")
    expect(trackStopped).toBe(true)
    // Scanner panel unmounts after a successful scan.
    expect(screen.queryByTestId("report-scanner")).not.toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it("closes the scanner from its own close control", () => {
    render(<RecruiterOpenPage />)
    fireEvent.click(screen.getByTestId("recruiter-open-scan-button"))
    fireEvent.click(screen.getByTestId("report-scanner-close"))
    expect(screen.queryByTestId("report-scanner")).not.toBeInTheDocument()
  })
})

describe("RecruiterOpenPage — content", () => {
  it("renders the recruiter CTA", () => {
    render(<RecruiterOpenPage />)
    expect(screen.getByTestId("recruiter-cta")).toBeInTheDocument()
    expect(screen.getByTestId("recruiter-cta-request-vbr")).toHaveAttribute(
      "href",
      "/recruiters/request-vbr",
    )
  })

  it("explains the recruiter-safe guarantees without scores or rankings", () => {
    render(<RecruiterOpenPage />)
    const text = document.body.textContent ?? ""
    expect(text).toMatch(/never private files, recordings, scores, or rankings/i)
    expect(text).not.toMatch(/\d+\/100|trust score/i)
  })
})
