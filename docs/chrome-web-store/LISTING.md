# Chrome Web Store submission package — VeriBridge Website Proof Recorder

Draft prepared 2026-08-03 for extension version **1.0.0** (Manifest V3).
Everything below is copy-paste-ready for the Developer Dashboard. Items marked
**[USER DECISION]** need the publisher's confirmation before submission.

---

## 1. Store listing

| Field | Value |
|---|---|
| **Name** | VeriBridge Website Proof Recorder |
| **Short description** (≤132 chars) | Record a Website Proof session you start from VeriBridge and attach the evidence to your selected project. |
| **Category** | Tools (alternative: Education) **[USER DECISION]** |
| **Language** | English |
| **Homepage URL** | https://veribridgeai.com |
| **Support URL** | https://veribridgeai.com/extension/support |
| **Privacy policy URL** | https://veribridgeai.com/privacy — the canonical VeriBridge Privacy Policy (platform + extension; live since 2026-08-16 after the "Purple Nickel" rejection). Enter this in the item's **Privacy** tab → "Privacy policy" field; do NOT use the homepage, /extension (install help), or /dashboard/privacy (login-walled). https://veribridgeai.com/extension/privacy remains live as the extension-specific policy and is linked from /privacy. |
| **Support email** | support@veribridgeai.com — live 2026-08-04 via free ImprovMX forwarding (catch-all) to the publisher's monitored Gmail; replies come from the publisher's Gmail for now. Receive-only is sufficient for Chrome Web Store purposes; professional outbound sending FROM the domain is an OPTIONAL post-launch enhancement, not a release requirement. |

### Detailed description

```
VeriBridge Website Proof Recorder captures a short, student-initiated
demonstration of a project the student built, and attaches the resulting
evidence to that student's VeriBridge Work Passport project.

How it works
1. Sign in at veribridgeai.com and start a Website Proof for one of your
   projects.
2. The page connects to the recorder and opens your project website.
3. You start a screen recording using Chrome's standard screen picker —
   nothing records until you choose what to share.
4. Demonstrate your project. The recorder also captures visible page text,
   clicks, and screenshots on your demo site so reviewers can verify the
   workflow was real.
5. Stop the recording and send your proof. Evidence uploads only to
   VeriBridge and only into the proof session you started.

Privacy, by design
• Records nothing until you start a proof from your signed-in VeriBridge
  account, and stops when the session ends (5-minute recording cap).
• No audio, no camera, no cookies, no localStorage, no browsing history.
• Passwords and sensitive-looking fields (tokens, card numbers, one-time
  codes…) are masked in your browser before anything is uploaded.
• Evidence can only be uploaded to VeriBridge — the extension refuses any
  other destination.

This extension is only useful with a VeriBridge student account. Full privacy
policy: https://veribridgeai.com/privacy
```

### Single-purpose statement

> VeriBridge Website Proof Recorder has one purpose: to let a student capture a
> user-initiated Website Proof demonstration session (screen recording plus
> on-page evidence of the student's own project website) and securely attach
> that evidence to the student's selected project in their VeriBridge account.

---

## 2. Permission justifications (dashboard "Privacy practices" tab)

| Permission | Justification text |
|---|---|
| `storage` | Persists the active proof-session configuration and an in-progress recording's recovery state so a service-worker restart, tab crash, or browser restart cannot lose the student's recording before it is uploaded. |
| Host permission `https://*/*` (+ `http://localhost/*`, `http://127.0.0.1/*`) | A student demonstrates their own project website, whose address is unknown at install time and different for every student (any https origin, or a localhost dev server). While a proof session the student explicitly started is recording, the content script on the demo site captures visible page text, clicks, and screenshots that form the proof evidence, and the extension takes tab screenshots of the demo page. When no proof session is recording, the content script captures nothing. Narrower host patterns are impossible because each student's project URL is arbitrary and user-supplied at session time. |
| Remote code | None. All executable code ships in the package. The extension performs only data-plane HTTPS calls (JSON/media upload) to VeriBridge's API. |

Screen recording uses `navigator.mediaDevices.getDisplayMedia` in an
extension-owned page — user-gesture-gated by Chrome's own picker; no
`desktopCapture`/`tabCapture` permission is requested.

### Data-use disclosures (check exactly these)

Collected:
- **Website content** (page text, screenshots/video of the site the student demonstrates — only during a recording the student starts)
- **User activity** (clicks and form interactions on the demo site during recording)
- **Web history**: NOT collected (only URLs of pages visited *inside* the recording session are part of the evidence — declare under Website content/User activity context; no ambient history is read) **[reviewer nuance: URLs of recorded pages are stored with the proof]**
- **Personally identifiable information**: the student's own VeriBridge account/session identity binds evidence to their account
- **Authentication information**: a short-lived session token handed by the signed-in VeriBridge page, used only to upload the student's evidence to VeriBridge

Certify:
- ☑ Data is **not sold** to third parties
- ☑ Data is **not used or transferred for purposes unrelated** to the item's single purpose
- ☑ Data is **not used or transferred to determine creditworthiness** or for lending

---

## 3. Reviewer test instructions

```
This extension only functions together with a signed-in account on
https://veribridgeai.com (student role).

TEST ACCOUNT
Email:    [USER DECISION — provide a dedicated reviewer account]
Password: [USER DECISION]

STEPS
1. Sign in at https://veribridgeai.com/login with the test account.
2. Open https://veribridgeai.com/student/proofs/website
3. Fill the form:
   Website URL:      https://example.com   (any public https site works)
   Proof objective:  "Demonstrate the homepage"
   Skills:           "HTML"
4. Click "Start proof", then "▶ Start Proof Demo".
   • The extension opens the target site in a new tab and a recorder tab.
5. In the recorder tab click "Start Screen Recording", choose any surface in
   Chrome's picker, interact with the target site for ~15 seconds.
6. Click "Stop" (recorder tab or floating bar). The video uploads.
7. Back on the proof page, click Send/complete when offered.

WHAT TO VERIFY
• Nothing is recorded before step 5's Chrome screen-picker consent.
• The floating "VB" bar is visible on the recorded site during capture.
• All network traffic from the extension goes only to
  https://veribridge-api.onrender.com (VeriBridge's API).
• Uninstalling the extension removes all local state.

The extension is inert on ordinary browsing: without a started proof session
its content script captures nothing and sends nothing.
```

---

## 4. Assets

| Asset | Path | Size |
|---|---|---|
| Store icon | `apps/extension/store-assets/store-icon-128.png` | 128×128 (96px artwork + padding) |
| Small promo tile | `apps/extension/store-assets/promo-small-440x280.png` | 440×280 |
| Screenshots (1–5) | `apps/extension/store-assets/screenshot-*.png` | 1280×800 — captured during real-browser QA |

Package icons (in the ZIP): `icons/icon{16,32,48,128}.png`.

---

## 5. Distribution

| Setting | Value |
|---|---|
| Visibility | **Public** (recommended; "Unlisted" is a valid soft-launch alternative) **[USER DECISION]** |
| Regions | All regions |
| Pricing | Free |

---

## 6. Release package

Produced by `cd apps/extension && npm run package:release`:
- ZIP: `apps/extension/release/veribridge-recorder-v1.0.0.zip` (manifest.json at ZIP root)
- Checksum file alongside (`.sha256`)
- Contents: manifest.json, popup.html, recorder.html, dist/{background,content,popup,recorder}.js, icons/icon{16,32,48,128}.png — nothing else (no source, no tests, no node_modules, no maps, no keys)

## 7. Update & rollback strategy

- **Updates**: bump `manifest.json` version (and the shared contract
  `WEBSITE_PROOF_RECORDER_BUILD_VERSION`), rebuild the release ZIP, upload to the
  dashboard, submit for review. Chrome auto-updates installed users within
  hours of approval. The website accepts any build ≥
  `WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION`, so a staged store rollout never
  breaks users; raise the minimum only after an update is broadly deployed.
- **Rollback / withdrawal**: the dashboard's "Unpublish" removes the listing
  from the store (existing installs keep working). A bad build is rolled back
  by submitting a new higher-version package built from the last good tag.
  If the extension must be disabled outright, raise
  `WEBSITE_PROOF_RECORDER_MIN_BUILD_VERSION` above the bad build so the site
  routes users to the update screen.

## 8. Post-publication checklist

1. Copy the published listing URL (`https://chromewebstore.google.com/detail/<item-id>`).
2. Set `NEXT_PUBLIC_RECORDER_EXTENSION_STORE_URL` on Vercel (production) to that URL and redeploy the web app — the install screens switch from "release under review" to the Install button automatically.
3. Install from the real store listing and run the first-time flow end-to-end in production.
4. Confirm no developer-mode instructions are visible to ordinary students anywhere in the product.
