import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "VeriBridge Website Proof Recorder — privacy policy",
  description:
    "What the VeriBridge Website Proof Recorder extension collects, how it is used, stored, shared, and deleted.",
}

const h2: React.CSSProperties = { fontSize: 17, fontWeight: 800, margin: "26px 0 8px", color: "#1f2937" }
const p: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", margin: "0 0 10px" }
const li: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", marginBottom: 6 }

export default function ExtensionPrivacyPolicyPage() {
  return (
    <article>
      <h1 style={{ fontSize: 24, fontWeight: 800, margin: "0 0 4px", color: "#111827" }}>
        Website Proof Recorder — Privacy Policy
      </h1>
      <p style={{ ...p, color: "#6b7280" }}>Effective date: August 3, 2026</p>

      <p style={p}>
        The VeriBridge Website Proof Recorder (&quot;the recorder&quot;) is a browser
        extension with a single purpose: it records a demonstration session that
        <strong> you</strong> start from your signed-in VeriBridge account and attaches the
        resulting evidence to the VeriBridge project you selected. It does
        nothing until you start a Website Proof, and it stops when your proof
        session ends.
      </p>

      <h2 style={h2}>What the recorder collects — only during a proof session you start</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}><strong>Screen recording video</strong> of the tab, window, or screen you explicitly choose in Chrome&apos;s screen-share picker (no audio, no microphone, no camera).</li>
        <li style={li}><strong>On-page evidence from the website you demonstrate</strong>: visible page text, page titles, page URLs, clicks, and form interactions, so your evidence shows the real workflow.</li>
        <li style={li}><strong>Screenshots</strong> (still frames) of the demo tab at key moments, such as when a result appears.</li>
        <li style={li}><strong>File-upload metadata</strong> when your demo includes uploading a file: only the file type, extension, and a non-reversible hash of the name — never the file itself, its real name, or its location on your computer.</li>
        <li style={li}><strong>Basic browser metadata</strong>: browser user-agent string, language, and platform, recorded with the proof for authenticity.</li>
        <li style={li}><strong>Your VeriBridge session identity</strong>: evidence is bound to the proof session and account that started it, so it can never be attached to someone else.</li>
      </ul>

      <h2 style={h2}>What the recorder never collects</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>Nothing at all while you are not recording a proof session.</li>
        <li style={li}>No cookies, no localStorage or sessionStorage contents, no browsing history.</li>
        <li style={li}>No passwords or sensitive fields: password inputs and fields that look like tokens, API keys, card numbers, bank details, SSNs, or one-time codes are replaced with a redaction marker <em>before</em> anything leaves your browser. URLs with sensitive query parameters are redacted the same way. VeriBridge&apos;s servers run a second, independent privacy scan on everything received.</li>
        <li style={li}>No audio or camera capture of any kind.</li>
      </ul>

      <h2 style={h2}>Authentication</h2>
      <p style={p}>
        When you start a proof, the VeriBridge page you are signed in to hands the
        recorder a short-lived access token for your own session. The token is
        accepted only from VeriBridge&apos;s own website, is used solely to upload
        your evidence to VeriBridge, is never shown to the website you are
        demonstrating, and expires with your sign-in session.
      </p>

      <h2 style={h2}>Where evidence goes, and where it does not</h2>
      <p style={p}>
        All evidence is uploaded over HTTPS to VeriBridge&apos;s own API — the
        recorder refuses to send data anywhere else. Every upload is checked
        server-side to confirm the proof session belongs to the signed-in account
        that created it.
      </p>

      <h2 style={h2}>Storage, retention, and sharing</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>Evidence is stored with your VeriBridge account and forms part of the proof you created.</li>
        <li style={li}>Your proofs are private to your account by default. They become visible to others only through the sharing and disclosure choices you make in VeriBridge (for example publishing a Work Passport or sharing a report link).</li>
        <li style={li}>VeriBridge does not sell your data and does not share recorder data with advertisers or unrelated third parties.</li>
        <li style={li}>An in-progress recording is also held temporarily in the extension&apos;s local storage on your computer so a crash cannot lose it; it is removed once the upload is confirmed.</li>
      </ul>

      <h2 style={h2}>Your controls and deletion</h2>
      <ul style={{ paddingLeft: 20, margin: 0 }}>
        <li style={li}>Recording starts only from your explicit action and Chrome&apos;s own screen-share consent dialog, and you can stop it at any time (it also stops automatically after 5 minutes).</li>
        <li style={li}>Evidence uploads to your own private proof session when you stop the screen recording and when you press Send Proof — and your proof is not finalized until you send it.</li>
        <li style={li}>To delete a proof and its evidence, or to request deletion of all data associated with your account, contact us at the address below. Uninstalling the extension removes everything it stores locally.</li>
      </ul>

      <h2 style={h2}>Changes</h2>
      <p style={p}>
        If this policy changes, the effective date above is updated and material
        changes are announced in the product before they take effect.
      </p>

      <h2 style={h2}>Contact</h2>
      <p style={p}>
        VeriBridge — <a href="mailto:support@veribridgeai.com" style={{ color: "#4f46e5" }}>support@veribridgeai.com</a>
        <br />
        Support page: <Link href="/extension/support" style={{ color: "#4f46e5" }}>veribridgeai.com/extension/support</Link>
      </p>
    </article>
  )
}
