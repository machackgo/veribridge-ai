import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "VeriBridge Privacy Policy",
  description:
    "How VeriBridge collects, uses, stores, shares, and deletes information across the VeriBridge platform and the Website Proof Recorder Chrome extension.",
}

const h2: React.CSSProperties = { fontSize: 18, fontWeight: 800, margin: "30px 0 8px", color: "#1f2937" }
const h3: React.CSSProperties = { fontSize: 15, fontWeight: 700, margin: "18px 0 6px", color: "#1f2937" }
const p: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", margin: "0 0 10px" }
const li: React.CSSProperties = { fontSize: 14, lineHeight: 1.7, color: "#374151", marginBottom: 6 }
const ul: React.CSSProperties = { paddingLeft: 20, margin: "0 0 10px" }
const a: React.CSSProperties = { color: "#4f46e5" }

export default function PrivacyPolicyPage() {
  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", color: "#111827" }}>
      <header
        style={{
          borderBottom: "1px solid #e5e7eb",
          background: "#fff",
          padding: "14px 20px",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <Link href="/" style={{ fontWeight: 800, fontSize: 15, color: "#312e81", textDecoration: "none" }}>
          VeriBridge
        </Link>
        <span style={{ color: "#9ca3af", fontSize: 13 }}>/</span>
        <span style={{ fontSize: 13, color: "#4b5563", fontWeight: 600 }}>Privacy Policy</span>
      </header>

      <main style={{ maxWidth: 760, margin: "0 auto", padding: "32px 20px 64px" }}>
        <article>
          <h1 style={{ fontSize: 26, fontWeight: 800, margin: "0 0 4px", color: "#111827" }}>
            VeriBridge Privacy Policy
          </h1>
          <p style={{ ...p, color: "#6b7280" }}>Effective date: August 16, 2026 · Last updated: August 16, 2026</p>

          <p style={p}>
            This Privacy Policy explains what information VeriBridge collects, why we
            collect it, how it is used, stored, and shared, and the controls you have.
            It covers the VeriBridge platform at{" "}
            <Link href="/" style={a}>veribridgeai.com</Link>, the VeriBridge API, and
            the <strong>VeriBridge Website Proof Recorder</strong> Chrome extension
            (see the <a href="#extension" style={a}>extension section</a> below and the
            extension-specific policy at{" "}
            <Link href="/extension/privacy" style={a}>veribridgeai.com/extension/privacy</Link>).
          </p>

          <h2 style={h2}>What VeriBridge is</h2>
          <p style={p}>
            VeriBridge is a platform where students build a verified <em>Work
            Passport</em>: a profile backed by real evidence of their skills. Students
            create <em>proofs</em> — uploaded documents, recorded project
            demonstrations, linked GitHub repositories, and screen-recorded website
            demos — which VeriBridge analyzes into verified skill reports. Students
            choose what to publish; recruiters can view published passports and
            reports and connect with candidates.
          </p>

          <h2 style={h2}>Information we collect</h2>

          <h3 style={h3}>Account and authentication information</h3>
          <ul style={ul}>
            <li style={li}>Your email address and basic account identity.</li>
            <li style={li}>
              If you sign in with Google, the identity information Google shares for
              sign-in (name, email, avatar). If you sign in with email, we send
              one-time sign-in codes/links to your address. VeriBridge does not store
              passwords.
            </li>
            <li style={li}>
              Session tokens used to keep you signed in and to authorize your requests.
            </li>
          </ul>

          <h3 style={h3}>Profile and passport content you provide</h3>
          <ul style={ul}>
            <li style={li}>
              Profile details you add to your Work Passport, such as your name, photo,
              education, headline, and the skills and projects you describe.
            </li>
          </ul>

          <h3 style={h3}>Evidence you create (proofs)</h3>
          <ul style={ul}>
            <li style={li}>
              <strong>Documents</strong> you upload as proof (for example certificates
              or reports).
            </li>
            <li style={li}>
              <strong>Video recordings</strong> you make when defending or
              demonstrating a project, and transcripts generated from them (you can
              correct transcripts; corrections are stored too).
            </li>
            <li style={li}>
              <strong>GitHub repository data</strong> for repositories you choose to
              link, such as commit history, file contents, and contribution metadata,
              used to generate skill evidence.
            </li>
            <li style={li}>
              <strong>Website Proof recordings</strong> captured with the Website
              Proof Recorder extension — see the{" "}
              <a href="#extension" style={a}>extension section</a> below.
            </li>
            <li style={li}>
              Analysis results derived from your evidence (skill assessments, report
              content) become part of your account data.
            </li>
          </ul>

          <h3 style={h3}>Recruiter account information</h3>
          <ul style={ul}>
            <li style={li}>
              Recruiters provide their email and profile details (such as name and
              company), and VeriBridge stores the candidates they save and the
              passports they connect with.
            </li>
          </ul>

          <h3 style={h3}>Visitor and view information on published pages</h3>
          <ul style={ul}>
            <li style={li}>
              When someone opens a published Work Passport, public report, passport
              card, or share link, we record a view event. Depending on the surface,
              this can include the visitor&apos;s IP address, browser user-agent,
              referring page, and how the link was reached (for example a QR-code
              scan). We use this to show passport owners how their published pages
              are being viewed and to prevent abuse.
            </li>
          </ul>

          <h3 style={h3}>Support communications</h3>
          <ul style={ul}>
            <li style={li}>
              If you email <a href="mailto:support@veribridgeai.com" style={a}>support@veribridgeai.com</a>,
              we receive your message and email address so we can respond.
            </li>
          </ul>

          <h2 style={h2} id="extension">The Website Proof Recorder Chrome extension</h2>
          <p style={p}>
            The Website Proof Recorder is a Chrome extension with a single purpose: it
            records a demonstration session that <strong>you</strong> start from your
            signed-in VeriBridge account and attaches the resulting evidence to the
            VeriBridge project you selected. It collects nothing while you are not
            recording a proof session. The full extension-specific policy is at{" "}
            <Link href="/extension/privacy" style={a}>veribridgeai.com/extension/privacy</Link>{" "}
            and is incorporated into this policy.
          </p>

          <h3 style={h3}>What the extension collects — only during a proof session you start</h3>
          <ul style={ul}>
            <li style={li}>
              <strong>Screen recording video</strong> of the tab, window, or screen
              you explicitly choose in Chrome&apos;s screen-share picker (no audio, no
              microphone, no camera). Recording stops when you stop it and is capped
              at 5 minutes.
            </li>
            <li style={li}>
              <strong>On-page evidence from the website you demonstrate</strong>:
              visible page text, page titles, page URLs, clicks, and form
              interactions, so your evidence shows the real workflow.
            </li>
            <li style={li}>
              <strong>Screenshots</strong> (still frames) of the demo tab at key
              moments.
            </li>
            <li style={li}>
              <strong>File-upload metadata</strong> when your demo includes uploading
              a file: only the file type, extension, and a non-reversible hash of the
              name — never the file itself.
            </li>
            <li style={li}>
              <strong>Basic browser metadata</strong> (user-agent, language, platform)
              recorded with the proof for authenticity.
            </li>
            <li style={li}>
              <strong>Your VeriBridge session identity</strong>: a short-lived access
              token handed to the extension by the VeriBridge page you are signed in
              to, used solely to upload your evidence to your own proof session.
            </li>
          </ul>

          <h3 style={h3}>What the extension never collects</h3>
          <ul style={ul}>
            <li style={li}>Nothing at all while you are not recording a proof session.</li>
            <li style={li}>No cookies, no localStorage or sessionStorage contents, no browsing history.</li>
            <li style={li}>
              No passwords or sensitive fields: password inputs and fields that look
              like tokens, API keys, card numbers, bank details, or one-time codes are
              replaced with a redaction marker <em>before</em> anything leaves your
              browser, and URLs with sensitive query parameters are redacted the same
              way. VeriBridge&apos;s servers run a second, independent privacy scan on
              everything received.
            </li>
            <li style={li}>No audio or camera capture of any kind.</li>
          </ul>

          <h3 style={h3}>Extension permissions and why they are required</h3>
          <ul style={ul}>
            <li style={li}>
              <strong><code>storage</code></strong> — keeps the active proof-session
              configuration and an in-progress recording&apos;s recovery state on your
              computer so a crash or browser restart cannot lose your recording
              before upload. This local state is removed once the upload is
              confirmed, and uninstalling the extension removes everything it stores.
            </li>
            <li style={li}>
              <strong>Host access (<code>https://*/*</code> and localhost)</strong> —
              you demonstrate your own project website, whose address is different
              for every student and unknown at install time, so the content script
              must be able to run on the site you choose. It captures nothing unless
              a proof session you started is actively recording.
            </li>
            <li style={li}>
              The extension requests no other permissions, runs no remote code, and
              uploads evidence only to VeriBridge&apos;s own API — it refuses to send
              data anywhere else.
            </li>
          </ul>

          <h2 style={h2}>Why we process this information</h2>
          <ul style={ul}>
            <li style={li}><strong>To provide the service</strong>: build your proofs, analyze your evidence into skill reports, assemble your Work Passport, and let you share it.</li>
            <li style={li}><strong>To verify authenticity</strong>: evidence is bound to the account and session that created it so it can never be attached to someone else, and uploads are checked server-side for ownership.</li>
            <li style={li}><strong>To show owners engagement</strong>: view events let passport owners see how their published pages are viewed.</li>
            <li style={li}><strong>To keep the service secure</strong>: authentication, abuse prevention, and debugging.</li>
            <li style={li}><strong>To communicate with you</strong>: sign-in emails and replies to your support requests.</li>
          </ul>

          <h2 style={h2}>How information is transmitted and stored</h2>
          <ul style={ul}>
            <li style={li}>All data moves over HTTPS. Evidence uploads go only to VeriBridge&apos;s own API.</li>
            <li style={li}>
              Account data, evidence, and analysis results are stored in VeriBridge&apos;s
              database and file storage, hosted by our infrastructure providers listed
              below.
            </li>
            <li style={li}>
              An in-progress extension recording is also held temporarily in the
              extension&apos;s local storage on your computer so a crash cannot lose
              it; it is removed once the upload is confirmed.
            </li>
          </ul>

          <h2 style={h2}>Service providers we use</h2>
          <p style={p}>
            VeriBridge does not sell your data and does not share it with advertisers.
            We use no third-party advertising or analytics trackers on our pages. The
            following service providers process data on our behalf to run the product:
          </p>
          <ul style={ul}>
            <li style={li}><strong>Supabase</strong> — authentication, database, and file storage (where your account data and evidence live).</li>
            <li style={li}><strong>Vercel</strong> — hosts the VeriBridge web application.</li>
            <li style={li}><strong>Render</strong> — hosts the VeriBridge API and evidence processing.</li>
            <li style={li}><strong>Google</strong> — optional Google sign-in; our pages also load fonts from Google Fonts, which means your browser requests those files from Google when a page loads.</li>
            <li style={li}><strong>Resend</strong> — delivers transactional emails such as sign-in codes and confirmations.</li>
            <li style={li}><strong>ImprovMX</strong> — forwards email sent to our support address to our team&apos;s mailbox.</li>
            <li style={li}>
              <strong>AI processing providers (Anthropic, OpenAI)</strong> — where
              these capabilities are enabled, evidence you submit (such as recordings,
              transcripts, repository contents, and documents) may be processed by
              these providers on our behalf to generate transcripts and skill
              analyses. They act as processors for VeriBridge; we do not permit them
              to use your data for advertising.
            </li>
          </ul>
          <p style={p}>
            Beyond these providers, we disclose information only when you choose to
            share it (publishing a passport, sharing a report link) or if required by
            law.
          </p>

          <h2 style={h2}>Your controls and sharing choices</h2>
          <ul style={ul}>
            <li style={li}>Your proofs and passport are <strong>private to your account by default</strong>. They become visible to others only through the sharing and disclosure choices you make (publishing your Work Passport, sharing a report link or card, or granting access).</li>
            <li style={li}>A master visibility switch lets you take your entire public passport offline at any time, and granular disclosure settings control which sections and evidence appear publicly.</li>
            <li style={li}>Share links can be revoked, after which they stop resolving.</li>
            <li style={li}>Extension recording starts only from your explicit action plus Chrome&apos;s own screen-share consent dialog, and you can stop it at any time. Your proof is not finalized until you send it.</li>
          </ul>

          <h2 style={h2}>Retention and deletion</h2>
          <ul style={ul}>
            <li style={li}>Your account data, proofs, and evidence are retained while your account exists, so your Work Passport keeps working.</li>
            <li style={li}>
              To delete a proof and its evidence, or to request deletion of your
              account and all data associated with it, contact{" "}
              <a href="mailto:support@veribridgeai.com" style={a}>support@veribridgeai.com</a>.
            </li>
            <li style={li}>Uninstalling the extension removes everything it stores locally on your computer.</li>
          </ul>

          <h2 style={h2}>Security</h2>
          <p style={p}>
            All traffic is encrypted in transit with HTTPS. Evidence uploads are bound
            to the signed-in account and session that created them and are verified
            server-side. Sensitive-looking fields are redacted in your browser before
            upload, and our servers run an independent second privacy scan on received
            evidence. Access tokens handed to the extension are short-lived and are
            accepted only from VeriBridge&apos;s own website.
          </p>

          <h2 style={h2}>Children</h2>
          <p style={p}>
            VeriBridge is built for university students and recruiters and is not
            directed to children under 13. We do not knowingly collect information
            from children under 13.
          </p>

          <h2 style={h2}>Data sale and advertising</h2>
          <p style={p}>
            VeriBridge does not sell your personal information, does not use it for
            third-party advertising, and does not use or transfer it for purposes
            unrelated to the product&apos;s single purpose of building and sharing
            verified skill evidence you control.
          </p>

          <h2 style={h2}>Changes to this policy</h2>
          <p style={p}>
            If this policy changes, the effective date above is updated and material
            changes are announced in the product before they take effect.
          </p>

          <h2 style={h2}>Contact</h2>
          <p style={p}>
            VeriBridge —{" "}
            <a href="mailto:support@veribridgeai.com" style={a}>support@veribridgeai.com</a>
            <br />
            Extension support page:{" "}
            <Link href="/extension/support" style={a}>veribridgeai.com/extension/support</Link>
            <br />
            Extension-specific policy:{" "}
            <Link href="/extension/privacy" style={a}>veribridgeai.com/extension/privacy</Link>
          </p>
        </article>
      </main>
    </div>
  )
}
