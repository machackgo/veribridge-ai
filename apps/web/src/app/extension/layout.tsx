import type { ReactNode } from "react"
import Link from "next/link"
import { KeystoneMark } from "../../../components/brand"

export default function ExtensionPagesLayout({ children }: { children: ReactNode }) {
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
        <Link
          href="/"
          style={{
            fontWeight: 800,
            fontSize: 15,
            color: "#312e81",
            textDecoration: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <KeystoneMark size={20} tone="light" />
          VeriBridge
        </Link>
        <span style={{ color: "#9ca3af", fontSize: 13 }}>/</span>
        <span style={{ fontSize: 13, color: "#4b5563", fontWeight: 600 }}>Website Proof Recorder</span>
        <nav style={{ marginLeft: "auto", display: "flex", gap: 16 }}>
          <Link href="/extension" style={{ fontSize: 13, color: "#4f46e5", textDecoration: "none" }}>Install help</Link>
          <Link href="/extension/privacy" style={{ fontSize: 13, color: "#4f46e5", textDecoration: "none" }}>Privacy</Link>
          <Link href="/extension/support" style={{ fontSize: 13, color: "#4f46e5", textDecoration: "none" }}>Support</Link>
        </nav>
      </header>
      <main style={{ maxWidth: 760, margin: "0 auto", padding: "32px 20px 64px" }}>{children}</main>
    </div>
  )
}
