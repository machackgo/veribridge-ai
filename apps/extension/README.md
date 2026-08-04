# VeriBridge Website Proof Recorder (Chrome extension)

Records a student-initiated Website Proof session — screen recording plus
on-page evidence — and attaches it to the student's selected VeriBridge
project.

Current version: **1.0.0** (Manifest V3, recorder schema `1`).

## Build channels

| Channel | Command | Behavior |
|---|---|---|
| Dev | `npm run build` / `npm run dev` | Trusts localhost app routes; accepts loopback API bases. Load unpacked for local work. |
| Release | `npm run build:release` | Store channel: production app origins only; uploads pinned to the production API. |
| Store ZIP | `npm run package:release` | Clean release build → deterministic ZIP + SHA-256 under `release/`. |

Store listing materials live in `../../docs/chrome-web-store/LISTING.md`;
listing assets in `store-assets/`.

## Dev setup

```bash
cd apps/extension
npm ci
npm test           # contract + bridge + lifecycle + recovery + init gates
npm run build      # dev-channel build → dist/
npm run typecheck  # TypeScript check only
python3 scripts/generate-icons.py   # regenerate icons/ + store-assets/
```

## Loading in Chrome (developers)

1. `npm run build` to produce `dist/`
2. Open `chrome://extensions`, enable **Developer mode**
3. Remove or disable historical VeriBridge unpacked copies
4. **Load unpacked** → select this `apps/extension` folder (the one containing
   `manifest.json`)
5. After edits: **Reload** the extension, then refresh the Website Proof page

Students never do this — they install from the Chrome Web Store listing, and
the website's install screen (`RecorderInstallGate`) links them there.

## Usage

1. Create a Website Proof session from the authenticated VeriBridge page.
2. Click **Start Proof Demo**. The page confirms config, target readiness, and
   recording start for that exact session/revision.
3. In the automatically opened Recorder tab, start screen capture.
4. Demonstrate the target workflow, then stop screen capture and wait for the
   replay upload to succeed.
5. Stop recording and optionally add a final note in the extension popup.
6. Click **Send Proof**. Sending remains blocked until replay retention succeeds.

Session ID, API base, auth, project, URL, objective, and claimed skills are
read-only projections of the single acknowledged background configuration.
They are never manually pasted into the popup.

## Version compatibility

The web app sends `expected_build_version` as a MINIMUM
(`WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION` in
`packages/shared/websiteProofRecorderContract.ts`); the extension accepts any
page whose minimum is ≤ its own manifest version with a matching
`schema_version`. Never compare builds exactly — store updates roll out on
Chrome's schedule.

## Permissions (production package)

- `storage` — session config + crash-safe recording recovery state
- host `https://*/*`, `http://localhost/*`, `http://127.0.0.1/*` — the
  student's demo site is arbitrary and user-supplied; the content script
  captures evidence there only while a recording is active
- Screen capture via `getDisplayMedia` in the recorder tab (user gesture, no
  `desktopCapture` permission)

## Privacy

- Passwords and fields matching token/secret/api-key/card/cvv/ssn/otp/2fa/mfa
  patterns are replaced with `[REDACTED]` before leaving the browser
- Cookies, localStorage, and sessionStorage are **never** collected
- No audio or camera capture
- Uploads go only to allowlisted VeriBridge API origins
  (`isAllowedRecorderApiBase`)
- Public policy: https://veribridgeai.com/extension/privacy

## File structure

```
apps/extension/
├── manifest.json          Manifest V3 (icons, storage-only permissions)
├── popup.html / popup.ts  Extension popup UI
├── recorder.html / src/recorder.ts   Recorder tab (getDisplayMedia + durable upload)
├── src/background.ts      Service worker — state, gates, evidence upload
├── src/content.ts         Content script — evidence capture + app bridge
├── src/recorderBridge.ts  Window↔background bridge (trust gating)
├── src/buildChannel.ts    __VB_DEV_BUILD__ channel flag
├── src/recorderFinalize.ts / recorderMediaStore.ts   Durable finalize pipeline
├── icons/                 Package icons (generated)
├── store-assets/          Store icon, promo tile, screenshots
├── scripts/               build/test/package/icon tooling
└── dist/                  Built JS (gitignored)
```

## Upload endpoints

- `POST /api/v1/student/extension-proof/sessions/{id}/upload` — workflow events
- `POST .../workflow/visible-evidence` — DOM evidence batch
- `POST .../workflow/visual-frames` — screenshot frames
- `POST .../workflow/video` — WebM screen recording (≤100 MB, ≤5 min)

All carry `Authorization: Bearer <short-lived session token>` and are
ownership-checked server-side.
