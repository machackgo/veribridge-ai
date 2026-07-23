"use client"

import { PageHeader } from "../../../../../../components/passport/shared"
import { PassportProfileEditor } from "./PassportProfileEditor"

export default function Page() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <PageHeader
        eyebrow="Work Passport · Profile"
        title="Passport Profile"
        description="The identity recruiters see at the top of your public Work Passport. Every field is optional — empty fields are simply omitted, and you control what is published."
      />
      <PassportProfileEditor />
    </div>
  )
}
