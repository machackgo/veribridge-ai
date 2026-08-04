# Release QA evidence — VeriBridge Website Proof Recorder v1.0.0

Run 2026-08-03/04 against the local stack (web :3000, api :8000 at the fixed
backend, docker `e2e-supabase` rig) and real browsers.

## Automated suites

| Suite | Result |
|---|---|
| Extension unit tests (`apps/extension`, incl. new init-gate suite) | 69/69 pass |
| Extension typecheck + dev/release builds | clean |
| Web unit tests (`apps/web`, full vitest) | 1771/1771 pass |
| Web `tsc --noEmit` + `next build` (includes new /extension routes) | clean |
| API recorder/security suites (incl. new ownership tests) | 164 pass (agent run) + 114 pass (verification run) |

## Release-build security QA — real Chromium, unpacked store file set
`apps/extension/scripts/qa-release-browser.mjs` — **8/8 PASS**
- Detection PONG on production origin (schema 1, build 1.0.0, trusted, valid)
- INIT with arbitrary https API base → NACK `invalid_api_base`
- INIT with production API base → ACK
- Older page minimum (0.9.0) accepted by 1.0.0 build; newer minimum → `extension_version_incompatible`
- Release channel: NO bridge on localhost app routes (ping + init both silent)
- Foreign https origin: bridge fully silent

## First-time / installed / returning flows — real browsers, local stack
First-time (Playwright Chromium, no extension) — **5/5 PASS**: OTP login,
proactive install gate, safe "release under review" state (no broken store
link), 3-second fast-fail after Start Proof Demo, session context preserved.

Installed (real branded Chrome 151, isolated profile, unpacked v1.0.0 loaded
by the publisher, REAL `getDisplayMedia` screen capture): recorder handshake,
target tab, floating VB bar, screen capture stream active, durable finalize.
Backend log for session `089bf64d`: `workflow/video → 202`,
`visible-evidence → 202`, final `upload → 200`; DB shows retained
`website_replay_video` artifact, `video/webm`, 1,084,181 bytes. Recorder tab
ended at "✓ Uploaded". (One scripted check flagged only because its 60s wait
expired mid-upload; the upload completed and was verified server-side.)

A parallel pipeline run with a synthetic capture source (Playwright Chromium,
canvas stream) exercised the same full chain end-to-end — 202/202/200 —
proving the minimized permission set (`storage` only + host permissions)
still supports `captureVisibleTab` frames, tab tracking, and all uploads.

Returning user (same browser, extension present) — **1/1 PASS**: no install
prompt.

## Known environment limitations
- macOS TCC denies screen capture to Playwright's Chromium; real-capture QA
  therefore ran in branded Chrome (which students actually use). Grant
  Screen Recording to `~/Library/Caches/ms-playwright/chromium-*/…/Chromium.app`
  to make the full flow repeatable headlessly.
- Edge compatibility not exercised (Edge not installed on the QA machine);
  Edge is Chromium-based and installs from the Chrome Web Store.
- Next.js DEV-mode only: fresh cross-document navigation to a session view
  can render blank (pre-existing app-wide dev hydration quirk, tracked as
  QA-D-003 since 2026-07-18; production builds unaffected).

## Support-contact verification (2026-08-04)
End-to-end forwarding to the monitored inbox — **PASS**, two independent senders:
1. WPI Outlook → support@veribridgeai.com → destination Gmail — delivered.
2. Gmail (publisher's second account) → support@veribridgeai.com → destination Gmail — delivered (first message landed in Spam as expected for a brand-new forwarding domain; marked "Not spam").

Infrastructure: GoDaddy DNS (authoritative) → MX mx1/mx2.improvmx.com + SPF include:spf.improvmx.com → free ImprovMX catch-all → monitored Gmail. Receive-only; replies come from the publisher's Gmail (outbound-from-domain is an optional post-launch enhancement).

## Release package
- `release/veribridge-recorder-v1.0.0.zip`, 57.9 KB, 11 files, manifest at root
- SHA-256 `4702db28bfc5b6ad34c0f68eb00b670b65b758f09e1651b1f1557102e2aaea32`
  (byte-identical across repeated builds — deterministic)
- Guard rails: no sourcemaps, no secrets markers, no dev-channel flag
