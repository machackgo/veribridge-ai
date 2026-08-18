"use client"

/**
 * Voice input for recruiter search — a thin, privacy-first wrapper around the
 * browser's native Web Speech API (SpeechRecognition / webkitSpeechRecognition).
 *
 * Architecture decision: speech-to-text happens ENTIRELY through the
 * browser's own capability, as a progressive enhancement.
 *   - No audio ever reaches a VeriBridge server; we never record, store, or
 *     log audio. The only artifact is the TEXT transcript, which lands in
 *     the visible search box for the recruiter to review/edit before (or
 *     while) it is used — identical in privacy terms to typing.
 *   - The microphone starts only on an explicit click, runs one utterance
 *     (continuous=false), and stops itself; there is no background listening.
 *   - Unsupported browsers keep fully functional typed search.
 */

import { useCallback, useEffect, useRef, useState } from "react"

export type SpeechStatus =
  | "idle"
  | "listening"
  | "denied"
  | "error"
  | "unsupported"

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error?: string }) => void) | null
  onend: (() => void) | null
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<{
    isFinal: boolean
    0: { transcript: string }
  }>
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export interface UseSpeechRecognitionOptions {
  /** Live transcript (interim + final so far) — mirror it into the input. */
  onTranscript: (text: string) => void
  /** Recognition ended with a non-empty final transcript. */
  onFinal: (text: string) => void
}

export function useSpeechRecognition({
  onTranscript,
  onFinal,
}: UseSpeechRecognitionOptions) {
  // Support detection runs POST-hydration: the server always renders the
  // no-mic markup, and the first client render must match that HTML exactly
  // (computing support during render caused a hydration mismatch on every
  // speech-capable browser). The mic appears right after mount.
  const [status, setStatus] = useState<SpeechStatus>("unsupported")
  useEffect(() => {
    if (getSpeechRecognitionCtor()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- post-hydration capability detection
      setStatus("idle")
    }
  }, [])
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const finalRef = useRef("")
  // Keep latest callbacks without re-creating the recognition session.
  const onTranscriptRef = useRef(onTranscript)
  const onFinalRef = useRef(onFinal)
  useEffect(() => {
    onTranscriptRef.current = onTranscript
    onFinalRef.current = onFinal
  })

  const supported = status !== "unsupported"

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort()
      recognitionRef.current = null
    }
  }, [])

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const start = useCallback(() => {
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) {
      setStatus("unsupported")
      return
    }
    if (recognitionRef.current) recognitionRef.current.abort()

    const recognition = new Ctor()
    recognition.lang =
      typeof navigator !== "undefined" && navigator.language
        ? navigator.language
        : "en-US"
    recognition.continuous = false
    recognition.interimResults = true
    recognition.maxAlternatives = 1
    finalRef.current = ""

    recognition.onresult = (event) => {
      let interim = ""
      let final = ""
      for (let i = 0; i < event.results.length; i += 1) {
        const result = event.results[i]
        if (!result) continue
        if (result.isFinal) final += result[0].transcript
        else interim += result[0].transcript
      }
      finalRef.current = final.trim()
      const live = `${final} ${interim}`.replace(/\s+/g, " ").trim()
      if (live) onTranscriptRef.current(live)
    }
    recognition.onerror = (event) => {
      recognitionRef.current = null
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setStatus("denied")
      } else if (event.error === "no-speech" || event.error === "aborted") {
        setStatus("idle")
      } else {
        setStatus("error")
      }
    }
    recognition.onend = () => {
      recognitionRef.current = null
      setStatus((current) =>
        current === "listening" ? "idle" : current,
      )
      const finalText = finalRef.current
      if (finalText) onFinalRef.current(finalText)
    }

    try {
      recognition.start()
      recognitionRef.current = recognition
      setStatus("listening")
    } catch {
      recognitionRef.current = null
      setStatus("error")
    }
  }, [])

  return { status, supported, start, stop }
}
