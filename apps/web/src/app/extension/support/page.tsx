import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "VeriBridge Website Proof Recorder — support",
  description:
    "Troubleshooting and support for the VeriBridge Website Proof Recorder Chrome extension.",
}

const h2: React.CSSProperties = { fontSize: 17, fontWeight: 800, margin: "26px 0 8px", color: "#1f2937" }
const p: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", margin: "0 0 10px" }
const li: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", marginBottom: 8 }

export default function ExtensionSupportPage() {
  return (
    <article>
      <h1 style={{ fontSize: 24, fontWeight: 800, margin: "0 0 6px", color: "#111827" }}>
        Website Proof Recorder — Support
      </h1>
      <p style={{ ...p, color: "#6b7280" }}>
        Quick fixes for the most common recorder issues. Still stuck? Email{" "}
        <a href="mailto:support@veribridgeai.com" style={{ color: "#4f46e5" }}>support@veribridgeai.com</a>{" "}
        and include the diagnostic code (it looks like <code>WPR-…</code>) shown with any error.
      </p>

      <h2 style={h2}>&quot;The extension was not detected&quot;</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>Confirm it is installed and enabled: open <code>chrome://extensions</code> and check <strong>VeriBridge Website Proof Recorder</strong> is listed and switched on.</li>
        <li style={li}>If you installed it while the VeriBridge tab was already open, click <strong>&quot;I&apos;ve installed it — check again&quot;</strong> on the install screen, or refresh the page.</li>
        <li style={li}>Make sure you are using desktop Chrome or another Chromium browser — Firefox, Safari, and mobile browsers are not supported.</li>
      </ul>

      <h2 style={h2}>&quot;The recorder is out of date&quot;</h2>
      <p style={p}>
        Chrome updates extensions automatically within a few hours. To force it now:
        open <code>chrome://extensions</code>, turn on <strong>Developer mode</strong> (top right),
        and click <strong>Update</strong>. Then retry your proof.
      </p>

      <h2 style={h2}>&quot;The extension was reloaded — refresh this page&quot;</h2>
      <p style={p}>
        Chrome updated the extension while your proof page was open. Refresh the
        VeriBridge tab — your proof session is saved and resumes where you left off.
      </p>

      <h2 style={h2}>The screen picker was cancelled or denied</h2>
      <p style={p}>
        Nothing was recorded. Click <strong>Start Screen Recording</strong> in the recorder
        tab to open the picker again. For workflows spanning several windows,
        choose <strong>Entire Screen</strong>.
      </p>

      <h2 style={h2}>The upload failed</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>Your recording is saved locally — click <strong>Retry Upload</strong> in the recorder tab; retries can never create duplicate evidence.</li>
        <li style={li}>If it says the recording isn&apos;t signed in, open the VeriBridge Website Proof page while signed in, then retry.</li>
        <li style={li}>Recordings longer than 5 minutes or larger than 100&nbsp;MB are rejected — record a shorter demo.</li>
      </ul>

      <h2 style={h2}>Data and deletion requests</h2>
      <p style={p}>
        What the recorder collects and how to delete it is covered in the{" "}
        <Link href="/extension/privacy" style={{ color: "#4f46e5" }}>privacy policy</Link>. For
        deletion of a proof or of all data linked to your account, email{" "}
        <a href="mailto:support@veribridgeai.com" style={{ color: "#4f46e5" }}>support@veribridgeai.com</a> from
        your account email address.
      </p>

      <h2 style={h2}>Installation help</h2>
      <p style={p}>
        Step-by-step instructions live on the{" "}
        <Link href="/extension" style={{ color: "#4f46e5" }}>installation help page</Link>.
      </p>
    </article>
  )
}
