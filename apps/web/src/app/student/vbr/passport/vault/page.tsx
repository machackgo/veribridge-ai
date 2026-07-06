"use client"

import { PageHeader } from "../../../../../../components/passport/shared"
import { ProofVaultView } from "./ProofVaultView"

export default function Page() {
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "48px 24px" }}>
      <PageHeader
        eyebrow="Proof Vault · private"
        title="Proof Vault"
        description="Review suggested attachments, unattached evidence, and every proof you own. This is your private maintenance area — nothing here appears on your public Passport."
      />
      <ProofVaultView />
    </div>
  )
}
