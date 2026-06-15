"use client"

import { useParams } from "next/navigation"
import { PublicReportView } from "./PublicReportView"

export default function Page() {
  const params = useParams<{ token: string }>()
  const token = Array.isArray(params.token) ? params.token[0] : params.token

  if (!token) return null

  return <PublicReportView token={token} />
}
