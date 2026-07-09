"use client"

import { BeamView } from "./BeamView"

/**
 * `/beam` — the premium full-screen Passport handoff surface (Phase 1).
 *
 * A short, top-level, memorable URL is intentional: the student types or
 * bookmarks `/beam`, holds the phone up, and the recruiter scans one QR that
 * opens the live public Passport with no login. Owner-only data loading happens
 * inside {@link BeamView}; the card face renders public-safe fields only.
 */
export default function Page() {
  return <BeamView />
}
