# Final publication runbook — after Google Trader verification succeeds

Estimated total: **40–50 minutes** (plus Google's review time, typically 1–3
business days). Begins ONLY once the Chrome Web Store developer account shows
Trader address verification complete. Everything referenced below is frozen in
this repo — no rebuilding needed.

State going in (all verified 2026-08-04):
- Registration fee: paid. Trader verification: pending publisher's Worcester
  address document (external blocker; ~10–12 days).
- ZIP: `apps/extension/release/veribridge-recorder-v1.0.0.zip`
  sha256 `4702db28bfc5b6ad34c0f68eb00b670b65b758f09e1651b1f1557102e2aaea32`
  (deterministic; re-verify with `shasum -a 256 -c release/…​.sha256`)
- Listing copy + disclosures + reviewer instructions: `LISTING.md` (this dir)
- Assets: `apps/extension/store-assets/` (icon, promo, 3 screenshots)
- Privacy/support URLs live: https://veribridgeai.com/extension/privacy · /extension/support
- Support inbox verified end-to-end: support@veribridgeai.com

## Steps (publisher at the dashboard, assistant guiding)

**A. Account finalization (~5 min)**
1. https://chrome.google.com/webstore/devconsole → Account tab.
2. Confirm Trader status verified; set publisher display name ("VeriBridge");
   confirm contact email is verified (link arrives by email).

**B. Create item + upload (~5 min)**
3. Items → **New item** → upload the ZIP above. Note the assigned **item ID**.
4. Confirm the dashboard shows v1.0.0, MV3, no manifest errors.

**C. Store listing tab (~10 min)** — paste from `LISTING.md` §1:
5. Name, short + detailed description, category (Tools), language (English).
6. Upload store icon, 3 screenshots, small promo tile from `store-assets/`.
7. Homepage `https://veribridgeai.com`, support URL `/extension/support`.

**D. Privacy tab (~10 min)** — paste from `LISTING.md` §2:
8. Single-purpose statement; permission justifications (storage + host).
9. Data-use checkboxes exactly as listed; certify the three attestations.
10. Privacy policy URL: `https://veribridgeai.com/extension/privacy`.

**E. Distribution + review info (~5 min)**
11. Visibility Public (or Unlisted for soft launch — publisher's call),
    all regions, free.
12. Reviewer test-account credentials + steps from `LISTING.md` §3
    (create the dedicated reviewer account first if not yet done —
    a student account on veribridgeai.com; budget 5 extra minutes).

**F. Pre-submission review gate (~5 min) — STOP**
13. Assistant compiles: exact name/version/checksum, permissions shown by the
    dashboard, disclosures, assets, URLs, visibility, any dashboard warnings.
14. **Publisher explicitly approves. Only then:**

**G. Submit (~2 min)**
15. Submit for review. Record timestamp, item ID, listing URL, review status.
16. Do NOT claim published while status is pending.

## After Google approves (separate ~15 min, whenever it lands)
17. Copy the public listing URL `https://chromewebstore.google.com/detail/<item-id>`.
18. Vercel (production env): set
    `NEXT_PUBLIC_RECORDER_EXTENSION_STORE_URL=<listing URL>` → redeploy web
    (`npx vercel deploy --prod --archive=tgz` from repo root). Install screens
    switch from "release under review" to the Install button automatically.
19. Install from the real listing in a clean Chrome profile; run one
    first-time Website Proof end-to-end in production.
20. Confirm no developer-mode instructions are user-visible anywhere.

## Rejection playbook
Capture Google's exact policy reason → fix the genuine issue → bump version
(manifest + `WEBSITE_PROOF_RECORDER_BUILD_VERSION`) → `npm run package:release`
→ re-run `scripts/qa-release-browser.mjs` → publisher reviews → resubmit.
Never evade policy; never resubmit without publisher review.
