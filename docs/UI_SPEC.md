# VeriBridge AI MVP UI_SPEC

## UI philosophy

VeriBridge should look like an audit-grade instrument, not a portfolio builder.

The UI should feel:
- calm
- forensic
- legible
- evidence-first
- recruiter-readable in 90 seconds

Avoid:
- student portfolio look
- AI-glow hype UI
- gamification
- dashboards before data exists
- scores/progress rings
- unnecessary motion

## MVP routes

Build now:
- `/`
- `/login`
- `/dashboard`
- `/setup/[projectId]`
- `/setup/[projectId]/prepare`
- `/session/[sessionId]`
- `/projects/[projectId]/status`
- `/projects/[projectId]/review`
- `/r/[token]`
- `/methodology`
- `/admin`

Do not build now:
- `/p/[handle]` skill passport
- university dashboard
- roadmap pages
- recruiter dashboard
- marketplace pages
- extension UI

## Student journey

1. Signup/login
2. Connect GitHub
3. Choose repository
4. Add deployed URL
5. Confirm generated claims
6. Prepare for recording
7. Record browser defense session
8. Processing/status page
9. Student review/preview
10. Publish/share report

## Recruiter journey

1. Open public tokenized report
2. Watch 60-second highlight
3. Scan authenticity checks
4. Scan claim cards
5. Click evidence chips
6. Leave recruiter CTA interest if useful

## Design system

Use:
- light mode MVP
- Inter for UI text
- IBM Plex Mono for evidence metadata
- paper-white background
- ink-dark text
- hairline borders
- no shadows at rest
- verification green only for verified states
- amber only for partial/note states
- neutral gray for not assessed
- blue only for links/evidence focus

Evidence chips are the signature UI element.

Examples:
- `[video 04:12]`
- `[commit a3f9e2]`
- `[transcript]`
- `[live check 200 OK]`

Every claim should visually connect to evidence.

## Recording UI

Use browser recording, not Chrome extension.

Recording page must include:
- consent gate before recording
- compatibility check: desktop Chrome/Edge preferred
- mic preflight
- camera preflight
- screen share preflight
- question card
- timer
- recording status
- chunk upload status
- webcam PiP
- pause between questions
- finish/finalize button
- recovery path if tab crashes

Do not use proctoring language.
Tone: “Talk like you are showing a teammate.”

Question card should show:
- question number
- question text
- target file/commit/url chip
- related claim chip
- previous/next buttons

## Processing UI

Show real stages, not fake progress percentage:
- Upload verified
- Extracting keyframes
- Transcribing
- Aligning transcript
- Evaluating answers
- Drafting report
- Human review

Each completed stage may show artifact counts.

## Report page UI

Above the fold must include:
- title: VeriBridge Verified Build Report
- candidate name
- project title
- repo link
- live app link if available
- session metadata line
- highlight clip
- short “what this is” explanation
- authenticity check row
- claim summary counts

Report claim card includes:
- tier chip
- claim text
- short evidence-backed explanation
- evidence chips
- notable quote if safe
- expand/collapse

Authenticity check card includes:
- check name
- result
- method
- detail
- evidence chips

Mandatory section:
- What this report does not verify

Footer:
- methodology link
- student-control note
- recruiter CTA

## Motion

Use motion only for:
- claim-card expand/collapse
- evidence chip click causing video seek and subtle flash
- processing stage checkmark
- publish success checkmark

Do not animate:
- page transitions
- numbers counting up
- recording screen decorations
- tier chips
- dashboards

Respect reduced motion.

## Free frontend tools

Allowed:
- Tailwind
- shadcn/ui + Radix, restyled
- Lucide icons
- Motion One or minimal CSS transitions
- Plyr or native video player
- React Hook Form + Zod
- idb-keyval for recorder recovery
- Playwright
- axe-core
- Sentry
- PostHog only for app funnel; avoid third-party tracking on public report page

Avoid now:
- React Flow
- fancy graph libraries
- onboarding tours
- command palette
- heavy dashboard libraries
- LogRocket/session replay

## Frontend architecture

Existing frontend structure must be inspected before implementation.

Expected component groups:
- design-system components
- report components
- recorder components
- wizard components
- admin components

Server-render public report if possible.
Client components only where needed:
- recorder
- video player/evidence chip interactions
- forms
- status polling

## MVP UI success criteria

Report page success:
- recruiter understands in 90 seconds what the student demonstrated
- evidence chips work
- no raw storage paths leak
- no scores or unsafe wording shown

Recorder success:
- first 5 users can complete recording with minimal help
- no session is lost due to upload/recovery failure
- user knows exactly what will be recorded and published

Dashboard success:
- student can start new verification
- student can see project status
- student can open review/publish flow

## UI tasks order

1. Design tokens and evidence chips
2. Setup wizard
3. Recorder preflight
4. Recorder session and chunk status
5. Public report page
6. Status/review/publish/dashboard/admin
7. Landing and methodology page

## Do not build

Do not build:
- skill passport UI before Report #1
- university charts
- roadmap UI
- recruiter comparison UI
- dark mode
- extension UI
- fancy animations