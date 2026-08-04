import type { Metadata } from "next"
import Link from "next/link"

import {
  RECORDER_EXTENSION_STORE_URL,
  isRecorderStoreListingLive,
} from "@/lib/recorder-extension-store"

export const metadata: Metadata = {
  title: "VeriBridge Website Proof Recorder — installation help",
  description:
    "How to install the VeriBridge Website Proof Recorder Chrome extension and what each permission is used for.",
}

const h2: React.CSSProperties = { fontSize: 17, fontWeight: 800, margin: "28px 0 8px", color: "#1f2937" }
const p: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", margin: "0 0 10px" }
const li: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", marginBottom: 6 }

export default function ExtensionInstallHelpPage() {
  const storeLive = isRecorderStoreListingLive()
  return (
    <article>
      <h1 style={{ fontSize: 24, fontWeight: 800, margin: "0 0 6px", color: "#111827" }}>
        Installing the VeriBridge Website Proof Recorder
      </h1>
      <p style={{ ...p, color: "#6b7280" }}>
        The recorder is a free browser extension that captures a demo of your own
        project — screen recording plus on-page evidence — and attaches it to the
        Website Proof session you start on VeriBridge.
      </p>

      {storeLive ? (
        <a
          href={RECORDER_EXTENSION_STORE_URL}
          target="_blank"
          rel="noreferrer"
          style={{
            display: "inline-block",
            background: "#4f46e5",
            color: "#fff",
            borderRadius: 10,
            padding: "12px 20px",
            fontSize: 15,
            fontWeight: 700,
            textDecoration: "none",
            margin: "8px 0 4px",
          }}
        >
          Install from the Chrome Web Store
        </a>
      ) : (
        <div
          style={{
            border: "1px solid #e5e7eb",
            background: "#fff",
            borderRadius: 10,
            padding: "12px 16px",
            fontSize: 14,
            color: "#4b5563",
            lineHeight: 1.6,
            margin: "8px 0 4px",
          }}
        >
          The Chrome Web Store release is currently being reviewed. Existing
          approved testers can keep using their installed recorder; public
          installation opens here as soon as the listing is live.
        </div>
      )}

      <h2 style={h2}>Supported browsers</h2>
      <p style={p}>
        Desktop <strong>Google Chrome</strong> and other Chromium browsers that can
        install Chrome Web Store extensions (for example Microsoft Edge). Firefox,
        Safari, and mobile browsers are not supported yet.
      </p>

      <h2 style={h2}>How installation works</h2>
      <ol style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>On VeriBridge, open <strong>Website Proof</strong> and click <strong>Start Proof Demo</strong>. If the recorder isn&apos;t installed, an installation screen appears.</li>
        <li style={li}>Click <strong>Install VeriBridge Recorder</strong> — the official Chrome Web Store listing opens.</li>
        <li style={li}>Click <strong>Add to Chrome</strong> and review Chrome&apos;s permission dialog.</li>
        <li style={li}>Return to the VeriBridge tab. The page detects the extension automatically (or click <strong>&quot;I&apos;ve installed it — check again&quot;</strong>) and your proof continues where you left off.</li>
      </ol>

      <h2 style={h2}>What each permission is for</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>
          <strong>&quot;Read and change your data on websites&quot;</strong> — while a proof
          you started is recording, the recorder captures visible page text,
          clicks, and screenshots on the website you are demonstrating, so your
          evidence shows the real workflow. When you are not recording, it
          captures nothing.
        </li>
        <li style={li}>
          <strong>Screen recording</strong> — uses Chrome&apos;s standard screen-share
          picker. Recording starts only after you choose what to share, and stops
          when you stop it (or automatically after 5 minutes).
        </li>
        <li style={li}>
          <strong>Storage</strong> — keeps your in-progress recording safe locally so a
          crashed tab or browser restart doesn&apos;t lose it before upload.
        </li>
      </ul>
      <p style={{ ...p, marginTop: 10 }}>
        Passwords and sensitive fields are masked before anything leaves your
        browser, and evidence can only be uploaded to VeriBridge. Full details are
        in the <Link href="/extension/privacy" style={{ color: "#4f46e5" }}>privacy policy</Link>.
      </p>

      <h2 style={h2}>Trouble installing?</h2>
      <p style={p}>
        See <Link href="/extension/support" style={{ color: "#4f46e5" }}>support and troubleshooting</Link>.
      </p>
    </article>
  )
}
