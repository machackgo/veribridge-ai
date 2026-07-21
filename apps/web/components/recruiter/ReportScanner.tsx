"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { parseReportLink, type ReportLinkParse } from "@/lib/report-link"

/**
 * Camera QR scanner for VeriBridge Verified Build Report links.
 *
 * Privacy/scope contract:
 *  - decoding is 100% local via the browser's native `BarcodeDetector` — no
 *    frame ever leaves the device, nothing is recorded or stored, and no
 *    face/identity processing of any kind happens;
 *  - the camera starts only after an explicit user action (the page-level
 *    "Scan a QR code" button mounts this component) and every exit path —
 *    successful scan, Close button, unmount — stops all camera tracks;
 *  - a decoded value is accepted only when `parseReportLink` says it is a
 *    VeriBridge report link/token; anything else shows "not a report QR" and
 *    scanning continues. The parent receives a validated parse, never a raw
 *    scanned string, so a QR can never redirect anywhere.
 *
 * When `BarcodeDetector` or camera access is unavailable the component
 * renders a graceful "use the paste box instead" state — scanning is never
 * required to open a report.
 */

type ScannerPhase =
  | "starting"
  | "scanning"
  | "denied"
  | "no_camera"
  | "unsupported"
  | "error"
  | "success"

const SCAN_INTERVAL_MS = 350

const PHASE_GUIDANCE: Record<ScannerPhase, string> = {
  starting: "Requesting camera access — your browser will ask for permission.",
  scanning: "Camera is on. Point it at a Verified Build Report QR code.",
  denied:
    "Camera permission was denied. You can allow camera access in your browser's site settings and try again — or paste the report link below instead.",
  no_camera:
    "No usable camera was found on this device. Paste the report link or token below instead.",
  unsupported:
    "This browser can't scan QR codes. Paste the report link or token below instead.",
  error: "The camera could not be started. Paste the report link below instead.",
  success: "Report QR recognized. Opening the report…",
}

interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<Array<{ rawValue: string }>>
}

function createDetector(): BarcodeDetectorLike | null {
  const ctor = (
    window as unknown as {
      BarcodeDetector?: new (options?: { formats?: string[] }) => BarcodeDetectorLike
    }
  ).BarcodeDetector
  if (!ctor) return null
  try {
    return new ctor({ formats: ["qr_code"] })
  } catch {
    try {
      return new ctor()
    } catch {
      return null
    }
  }
}

export function ReportScanner({
  onResult,
  onClose,
}: {
  /** Receives a VALIDATED report parse (never the raw scanned string). */
  onResult: (parse: Extract<ReportLinkParse, { ok: true }>) => void
  onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const doneRef = useRef(false)

  const [phase, setPhase] = useState<ScannerPhase>("starting")
  const [scanNote, setScanNote] = useState<string | null>(null)

  const stopCamera = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
  }, [])

  useEffect(() => {
    let cancelled = false

    const supported =
      typeof navigator !== "undefined" &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      typeof window !== "undefined" &&
      "BarcodeDetector" in window
    if (!supported) {
      setPhase("unsupported")
      return
    }

    const detector = createDetector()
    if (!detector) {
      setPhase("unsupported")
      return
    }

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop())
          return
        }
        streamRef.current = stream
        const video = videoRef.current
        if (video) {
          video.srcObject = stream
          try {
            const playing = video.play() as Promise<void> | undefined
            playing?.catch(() => {})
          } catch {
            // jsdom / autoplay restrictions — the detector loop still runs.
          }
        }
        setPhase("scanning")

        intervalRef.current = setInterval(() => {
          const target = videoRef.current
          if (!target || doneRef.current) return
          detector
            .detect(target)
            .then((codes) => {
              if (doneRef.current) return
              for (const code of codes ?? []) {
                const parse = parseReportLink(code?.rawValue ?? "")
                if (parse.ok) {
                  doneRef.current = true
                  stopCamera()
                  setPhase("success")
                  setScanNote(null)
                  onResult(parse)
                  return
                }
                if (code?.rawValue) {
                  setScanNote(
                    "That QR code is not a VeriBridge report link — still scanning.",
                  )
                }
              }
            })
            .catch(() => {
              // Transient decode failure (e.g. video not ready) — keep scanning.
            })
        }, SCAN_INTERVAL_MS)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const name = error instanceof DOMException ? error.name : ""
        if (name === "NotAllowedError" || name === "SecurityError") {
          setPhase("denied")
        } else if (name === "NotFoundError" || name === "OverconstrainedError") {
          setPhase("no_camera")
        } else {
          setPhase("error")
        }
      })

    return () => {
      cancelled = true
      stopCamera()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const close = () => {
    doneRef.current = true
    stopCamera()
    onClose()
  }

  const cameraActive = phase === "starting" || phase === "scanning"

  return (
    <div
      data-testid="report-scanner"
      data-phase={phase}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 14,
        borderRadius: 12,
        border: "1px solid #e6e8ef",
        background: "#f8f9fc",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#0a0e1a" }}>QR scanner</span>
        <button
          type="button"
          data-testid="report-scanner-close"
          onClick={close}
          style={{
            padding: "6px 12px",
            borderRadius: 8,
            border: "1px solid #e6e8ef",
            background: "#ffffff",
            color: "#0a0e1a",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Close scanner
        </button>
      </div>

      {cameraActive && (
        <video
          ref={videoRef}
          data-testid="report-scanner-video"
          muted
          playsInline
          aria-label="Live camera preview used only to detect a report QR code on this device. No video is recorded, stored, or uploaded."
          style={{
            width: "100%",
            maxHeight: 280,
            borderRadius: 10,
            background: "#0a0e1a",
            objectFit: "cover",
          }}
        />
      )}

      {/* Screen-reader-friendly live status; also the visible textual state. */}
      <p
        data-testid="report-scanner-status"
        role="status"
        aria-live="polite"
        style={{ fontSize: 12.5, color: "#3f4657", margin: 0, lineHeight: 1.55 }}
      >
        {PHASE_GUIDANCE[phase]}
        {scanNote ? ` ${scanNote}` : ""}
      </p>

      <p style={{ fontSize: 11.5, color: "#6b7280", margin: 0, lineHeight: 1.5 }}>
        Scanning happens entirely on your device. Camera frames are never uploaded,
        recorded, or analyzed for anything except the QR code, and the camera stops
        as soon as a code is found or you close the scanner.
      </p>
    </div>
  )
}
