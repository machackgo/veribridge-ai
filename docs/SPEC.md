# VeriBridge AI MVP SPEC

## Product decision

VeriBridge AI MVP is the Verified Build Report, not the old full passport, marketplace, university dashboard, Chrome extension, or local model system.

The MVP verifies one student project through:
1. GitHub repository evidence
2. Optional deployed URL evidence
3. Browser-recorded project defense session
4. Transcript/keyframe analysis
5. Evidence-linked public report

The goal is not to claim “the student 100% built this.”
The goal is to show that the student demonstrated command of the project through evidence-linked verification.

## Strict MVP scope

Build now:
- GitHub repo ingestion
- Project claim extraction
- Repo-specific question generation
- Browser-based recording using getDisplayMedia, mic, webcam PiP
- Chunked video upload
- Transcript generation
- Keyframe extraction
- Per-question judgment
- Deterministic checks
- Evidence items
- Verified Build Report
- Human/admin review gate
- Public tokenized report page
- Report view tracking

Do not build now:
- Chrome extension
- University dashboard
- Roadmap product
- Marketplace
- Local/open-source model zoo
- Recruiter dashboard
- ATS integrations
- Payments
- Multi-discipline support
- Fancy graph UI

## Core layers

1. Raw evidence layer
Stores immutable project evidence:
- GitHub facts
- deployed URL checks
- video chunks
- final session video
- transcript segments
- keyframes
- session telemetry

2. Verification/report layer
Stores:
- project claims
- session questions
- per-question judgments
- authenticity checks
- evidence items
- report claims
- report JSON
- admin review status

3. Skill passport layer
Later only.
Derived from published reports. Not built in MVP.

4. Market intelligence layer
Later only.
Aggregated, anonymized, k-thresholded insights. Not built in MVP.

## MVP user flow

Student:
1. Sign up
2. Connect GitHub
3. Pick repo
4. Add deployed URL if available
5. System analyzes repo
6. System proposes project claims
7. Student confirms/edits claims
8. System generates repo-specific questions
9. Student records browser-based defense session
10. System processes transcript/keyframes
11. System generates evidence-linked report
12. Admin/human reviews
13. Student previews and publishes
14. Student shares public report link

Recruiter:
1. Opens tokenized report link
2. Sees highlight clip
3. Sees authenticity checks
4. Sees claim cards with evidence chips
5. Clicks commit/video/transcript evidence
6. Can submit recruiter interest lead

## Evidence rule

Every recruiter-visible claim must have:
- at least one artifact evidence item, and
- at least one process evidence item

Artifact evidence examples:
- commit
- file
- diff
- repo stat
- deployed URL check

Process evidence examples:
- video segment
- transcript segment
- keyframe
- session telemetry

If a claim has only artifact evidence, it can be at most partially demonstrated.

## Tier labels

Allowed recruiter-visible tiers:
- Demonstrated
- Partially demonstrated
- Not assessed
- Insufficient evidence
- Inconsistency noted

Never use:
- fraud
- fake
- cheating
- dishonest
- risk score
- 100% built by student
- AI-generated as a verdict
- hire / do not hire recommendation

## Report structure

Public report must show:
- Candidate name
- Project name
- Repo link
- Deployed URL link if available
- Session metadata: duration, attempt count, question count, human-reviewed status
- 60-second highlight clip or manual selected segment
- Authenticity checks
- Claims table/cards
- Evidence chips
- What this report does not verify
- Methodology link
- Recruiter CTA

## Authenticity checks

MVP checks:
- commit authorship matches connected GitHub account
- fork status
- commit timeline shape
- deployed URL reachable
- deployed URL visible/matched during session if possible
- session chunk manifest complete
- re-record count disclosed

Checks must be factual, not accusatory.

## AI model strategy

Use APIs first:
- Claude/OpenAI for claim extraction, question generation, judgment, synthesis
- Whisper/AssemblyAI for transcription
- ffmpeg for keyframes
- deterministic Python code for checks and tier mapping

Do not build or self-host models in MVP.

## Backend principles

- FastAPI owns privileged actions
- Supabase is database/auth/storage
- Service role never exposed to frontend
- Public report served through API serializer, not direct table access
- All state transitions audited
- Jobs must be idempotent
- Derived data can be regenerated from raw evidence

## MVP database path

Existing migrations live in:
apps/api/app/db/migrations

Next migration:
049_verified_build_report_core.sql

## Acceptance goal

Report #1 is successful when:
- one project can be ingested
- claims/questions are generated
- one browser recording can be uploaded
- transcript/keyframes are processed
- evidence-linked report is generated
- report is admin-reviewed
- public /r/{token} page works
- evidence chips can point to commit/video/transcript evidence