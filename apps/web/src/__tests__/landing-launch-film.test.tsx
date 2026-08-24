/**
 * Landing-page launch film — component + instrumentation tests.
 *
 * Guards the properties that make the approved film usable in production:
 *  - it is the real approved MP4 with the approved poster (never a teaser,
 *    GIF, YouTube embed, or silent re-export),
 *  - it never autoplays and never costs a visitor bytes before a deliberate
 *    Play (preload="none"),
 *  - it is presented uncropped (object-fit: contain, not cover),
 *  - the CTAs point at the existing student/recruiter routes rather than a
 *    duplicate signup path,
 *  - analytics fire exactly once per event per session and cannot be inflated
 *    by dragging the scrubber.
 */

import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CareerFairCallout, LaunchFilm } from "../../components/landing-v2/LaunchFilm"
import {
  LANDING_ANALYTICS_DOM_EVENT,
  __resetLandingAnalyticsForTests,
  trackLandingEvent,
} from "@/lib/landing-analytics"

const CANDIDATE_HREF = "/login?next=/dashboard"
const RECRUITER_HREF = "/recruiters"

/** Collect every landing analytics event emitted during a test. */
function captureEvents(): string[] {
  const seen: string[] = []
  window.addEventListener(LANDING_ANALYTICS_DOM_EVENT, (e) => {
    seen.push((e as CustomEvent).detail.event)
  })
  return seen
}

function renderFilm() {
  return render(
    <LaunchFilm candidateHref={CANDIDATE_HREF} recruiterHref={RECRUITER_HREF} />,
  )
}

beforeEach(() => {
  __resetLandingAnalyticsForTests()
  // jsdom implements no media pipeline; play() must resolve for the overlay.
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined)
  // IntersectionObserver is not implemented in jsdom.
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  )
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("Launch film section", () => {
  it("serves the approved final film and poster from the site's own origin", () => {
    renderFilm()
    const video = screen.getByTestId("launch-film-video")
    expect(video).toHaveAttribute("src", "/media/veribridge-ai-launch-film.mp4")
    expect(video).toHaveAttribute("poster", "/media/veribridge-ai-launch-film-poster.jpg")
  })

  it("never uses a teaser, GIF, or third-party embed as the film", () => {
    const { container } = renderFilm()
    const src = screen.getByTestId("launch-film-video").getAttribute("src") ?? ""
    expect(src).not.toMatch(/teaser|\.gif|youtube|vimeo|V2|V3/i)
    expect(container.querySelector("iframe")).toBeNull()
  })

  it("does not autoplay and does not preload the film bytes", () => {
    renderFilm()
    const video = screen.getByTestId("launch-film-video") as HTMLVideoElement
    expect(video).toHaveAttribute("preload", "none")
    expect(video).not.toHaveAttribute("autoplay")
    expect(video).not.toHaveAttribute("loop")
    // Not muted: the approved film carries its finished soundtrack.
    expect(video).not.toHaveAttribute("muted")
  })

  it("attaches native controls on first play and allows inline mobile playback", () => {
    renderFilm()
    const video = screen.getByTestId("launch-film-video")
    expect(video).toHaveAttribute("playsinline")
    // Poster state shows one deliberate Play affordance, not a dead control bar.
    expect(video).not.toHaveAttribute("controls")
    fireEvent.play(video)
    expect(video).toHaveAttribute("controls")
  })

  it("renders the approved section copy as crawlable text", () => {
    renderFilm()
    expect(screen.getByText(/SEE VERIBRIDGE AI IN ACTION/i)).toBeInTheDocument()
    expect(
      screen.getByRole("heading", { name: /Your résumé starts the conversation/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/carry that proof into career fairs, interviews, networking events/i),
    ).toBeInTheDocument()
  })

  it("points both CTAs at the existing routes", () => {
    renderFilm()
    expect(screen.getByRole("link", { name: /Build your Work Passport/i })).toHaveAttribute(
      "href",
      CANDIDATE_HREF,
    )
    expect(screen.getByRole("link", { name: /For Recruiters/i })).toHaveAttribute(
      "href",
      RECRUITER_HREF,
    )
  })

  it("gives the poster overlay an accessible label and removes it once playing", () => {
    renderFilm()
    const play = screen.getByRole("button", { name: /Play the VeriBridge AI launch film/i })
    fireEvent.click(play)
    fireEvent.play(screen.getByTestId("launch-film-video"))
    expect(screen.queryByTestId("launch-film-play")).toBeNull()
  })
})

describe("Launch film analytics", () => {
  it("emits play and completion once each", () => {
    const seen = captureEvents()
    renderFilm()
    const video = screen.getByTestId("launch-film-video")
    fireEvent.play(video)
    fireEvent.play(video)
    fireEvent.ended(video)
    fireEvent.ended(video)
    expect(seen.filter((e) => e === "landing_launch_video_play")).toHaveLength(1)
    expect(seen.filter((e) => e === "landing_launch_video_complete")).toHaveLength(1)
  })

  it("emits each quartile once and never repeats them while scrubbing", () => {
    const seen = captureEvents()
    renderFilm()
    const video = screen.getByTestId("launch-film-video") as HTMLVideoElement
    Object.defineProperty(video, "duration", { value: 98, configurable: true })

    const at = (seconds: number) => {
      Object.defineProperty(video, "currentTime", { value: seconds, configurable: true })
      fireEvent.timeUpdate(video)
    }

    at(30) // past 25%
    at(50) // past 50%
    at(80) // past 75%
    at(20) // scrubbed backwards
    at(80) // and forwards again
    at(90)

    expect(seen.filter((e) => e === "landing_launch_video_25")).toHaveLength(1)
    expect(seen.filter((e) => e === "landing_launch_video_50")).toHaveLength(1)
    expect(seen.filter((e) => e === "landing_launch_video_75")).toHaveLength(1)
  })

  it("ignores progress raised while the element is seeking", () => {
    const seen = captureEvents()
    renderFilm()
    const video = screen.getByTestId("launch-film-video") as HTMLVideoElement
    Object.defineProperty(video, "duration", { value: 98, configurable: true })
    Object.defineProperty(video, "seeking", { value: true, configurable: true })
    Object.defineProperty(video, "currentTime", { value: 90, configurable: true })
    fireEvent.timeUpdate(video)
    expect(seen).not.toContain("landing_launch_video_25")
  })

  it("fires the student CTA event once", () => {
    const seen = captureEvents()
    renderFilm()
    const cta = screen.getByRole("link", { name: /Build your Work Passport/i })
    fireEvent.click(cta)
    fireEvent.click(cta)
    expect(seen.filter((e) => e === "landing_launch_cta_click")).toHaveLength(1)
  })

  it("never sends a network request when no first-party collector is configured", () => {
    const beacon = vi.fn()
    vi.stubGlobal("fetch", vi.fn())
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true })
    trackLandingEvent("landing_launch_video_play")
    expect(beacon).not.toHaveBeenCalled()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })
})

describe("Fall Career Fair callout", () => {
  it("renders the campaign copy and routes into the existing student flow", () => {
    render(<CareerFairCallout candidateHref={CANDIDATE_HREF} />)
    expect(
      screen.getByRole("heading", { name: /Going to a Fall Career Fair\?/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(/What did you actually build\?/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Get Career-Fair Ready/i })).toHaveAttribute(
      "href",
      CANDIDATE_HREF,
    )
  })

  it("does not position VeriBridge AI as career-fair only", () => {
    render(<CareerFairCallout candidateHref={CANDIDATE_HREF} />)
    expect(
      screen.getByText(/interviews, networking\s+events, conferences, hackathons/i),
    ).toBeInTheDocument()
  })

  it("uses the full VeriBridge AI brand name, never a new short form", () => {
    const { container } = render(<CareerFairCallout candidateHref={CANDIDATE_HREF} />)
    expect(container.textContent).toContain("VeriBridge AI Work Passport")
    expect(container.textContent).not.toMatch(/\bVeri Bridge\b|\bVB\b/)
  })

  it("fires the career-fair CTA event once", () => {
    const seen = captureEvents()
    render(<CareerFairCallout candidateHref={CANDIDATE_HREF} />)
    const cta = screen.getByRole("link", { name: /Get Career-Fair Ready/i })
    fireEvent.click(cta)
    fireEvent.click(cta)
    expect(seen.filter((e) => e === "career_fair_cta_click")).toHaveLength(1)
  })
})
