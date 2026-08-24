"use client"

/**
 * Official VeriBridge AI launch film — landing-page centerpiece.
 *
 * Sits directly under the hero. The approved master (1920×1080 H.264 High,
 * 30fps, 98s, AAC stereo) is served byte-for-byte from the site's own Vercel
 * CDN at /media/veribridge-ai-launch-film.mp4; its moov atom already precedes
 * mdat, so it streams and scrubs without any remux.
 *
 * Delivery rules that matter here:
 *  - preload="none" ⇒ the ~70 MB film costs a visitor ZERO bytes until they
 *    deliberately press Play. Only the poster loads with the page.
 *  - Native `controls` provide play/pause, volume/mute, scrubbing and
 *    fullscreen with the browser's own keyboard and mobile affordances —
 *    strictly more accessible than anything hand-rolled here. They are
 *    attached on first play so the poster state shows exactly ONE play
 *    affordance instead of a dead control bar behind the overlay.
 *  - No autoplay, muted or otherwise: the film has a scored soundtrack and a
 *    deliberate Play is the intended first interaction.
 *  - object-fit: contain + a 16/9 box ⇒ the frame is never cropped, never
 *    stretched, and never upscaled past its native 1920×1080.
 */

import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"
import { ProofDiamond } from "./brand"
import { trackLandingEvent } from "@/lib/landing-analytics"

const FILM_SRC = "/media/veribridge-ai-launch-film.mp4"
const FILM_POSTER = "/media/veribridge-ai-launch-film-poster.jpg"

/** Progress milestones, in ascending order, as fractions of duration. */
const PROGRESS_MARKS = [
  { at: 0.25, event: "landing_launch_video_25" },
  { at: 0.5, event: "landing_launch_video_50" },
  { at: 0.75, event: "landing_launch_video_75" },
] as const

export function LaunchFilm({
  candidateHref,
  recruiterHref,
}: {
  candidateHref: string
  recruiterHref: string
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const sectionRef = useRef<HTMLElement | null>(null)
  const [started, setStarted] = useState(false)

  /* ── Impression: fires once when the film is meaningfully on screen ── */
  useEffect(() => {
    const node = sectionRef.current
    if (!node || typeof IntersectionObserver === "undefined") return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          trackLandingEvent("landing_launch_video_impression")
          observer.disconnect()
        }
      },
      { threshold: 0.5 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  /* ── Deliberate Play from the poster overlay ── */
  const handleOverlayPlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    setStarted(true)
    // play() rejects if the gesture is lost or the source fails; the native
    // controls stay usable either way, so swallow rather than surface it.
    void video.play().catch(() => {})
  }, [])

  const handlePlay = useCallback(() => {
    setStarted(true)
    trackLandingEvent("landing_launch_video_play")
  }, [])

  /* ── Quartile progress. Guarded against seeking so dragging the scrubber
       cannot manufacture milestones, and each event is additionally deduped
       per session inside trackLandingEvent. ── */
  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current
    if (!video || video.seeking || !Number.isFinite(video.duration) || video.duration <= 0) {
      return
    }
    const ratio = video.currentTime / video.duration
    for (const mark of PROGRESS_MARKS) {
      if (ratio >= mark.at) trackLandingEvent(mark.event)
    }
  }, [])

  const handleEnded = useCallback(() => {
    trackLandingEvent("landing_launch_video_complete")
  }, [])

  return (
    <section className="lv-film" id="launch-film" ref={sectionRef} aria-labelledby="lv-film-title">
      <div className="lv-film-inner">
        <div className="lv-film-head">
          <p className="lv-eyebrow">
            <ProofDiamond state="verified" size={8} /> SEE VERIBRIDGE AI IN ACTION
          </p>
          <h2 className="lv-h2" id="lv-film-title">
            Your résumé starts the conversation.
            <br />
            <span className="lv-h2-accent">Your work should take it deeper.</span>
          </h2>
        </div>

        <div className="lv-film-stage">
          <div className="lv-film-frame">
            <video
              ref={videoRef}
              className="lv-film-video"
              src={FILM_SRC}
              poster={FILM_POSTER}
              controls={started}
              preload="none"
              playsInline
              width={1920}
              height={1080}
              onPlay={handlePlay}
              onTimeUpdate={handleTimeUpdate}
              onEnded={handleEnded}
              data-testid="launch-film-video"
            >
              Your browser does not support embedded video.{" "}
              <a href={FILM_SRC}>Download the VeriBridge AI launch film</a> to watch it.
            </video>
            {started ? null : (
              <button
                type="button"
                className="lv-film-play"
                onClick={handleOverlayPlay}
                aria-label="Play the VeriBridge AI launch film"
                data-testid="launch-film-play"
              >
                <span className="lv-film-play-mark" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="26" height="26" fill="currentColor">
                    <path d="M8 5.2v13.6a.8.8 0 0 0 1.22.68l11.02-6.8a.8.8 0 0 0 0-1.36L9.22 4.52A.8.8 0 0 0 8 5.2Z" />
                  </svg>
                </span>
                <span className="lv-film-play-label">
                  Watch the film
                  <span className="lv-film-play-meta">1 min 38 sec · sound on</span>
                </span>
              </button>
            )}
          </div>
        </div>

        <div className="lv-film-foot">
          <p className="lv-film-sub">
            Build a Work Passport from the projects you already have. Connect code,
            documents, live product demonstrations, and project evidence — then carry
            that proof into career fairs, interviews, networking events, and every
            opportunity after.
          </p>
          <div className="lv-film-ctas">
            <Link
              className="lv-btn lv-btn-primary lv-btn-lg"
              href={candidateHref}
              onClick={() => trackLandingEvent("landing_launch_cta_click")}
            >
              Build your Work Passport
            </Link>
            <Link className="lv-btn lv-btn-outline lv-btn-lg" href={recruiterHref}>
              For Recruiters
            </Link>
          </div>
        </div>
      </div>
    </section>
  )
}

/**
 * Fall Career Fair callout — a campaign entry point into the ordinary student
 * onboarding route, deliberately sized as a supporting note rather than a
 * second hero. VeriBridge AI is not a career-fair product; the copy above and
 * below keeps the broader use cases in view.
 */
export function CareerFairCallout({ candidateHref }: { candidateHref: string }) {
  return (
    <section className="lv-fair" aria-labelledby="lv-fair-title">
      <div className="lv-fair-inner">
        <div className="lv-fair-copy">
          <p className="lv-eyebrow">
            <ProofDiamond state="verified" size={8} /> THIS FALL
          </p>
          <h3 className="lv-fair-h" id="lv-fair-title">
            Going to a Fall Career Fair?
          </h3>
          <p className="lv-fair-sub">
            Don&apos;t walk in with only a résumé. Build your VeriBridge AI Work
            Passport, publish the proof behind your projects, and have your Passport
            ready when someone asks: “What did you actually build?”
          </p>
          <p className="lv-fair-note">
            The same Passport works long after the fair — interviews, networking
            events, conferences, hackathons, and every professional introduction
            after.
          </p>
        </div>
        <Link
          className="lv-btn lv-btn-primary lv-btn-lg lv-fair-cta"
          href={candidateHref}
          onClick={() => trackLandingEvent("career_fair_cta_click")}
        >
          Get Career-Fair Ready
        </Link>
      </div>
    </section>
  )
}
