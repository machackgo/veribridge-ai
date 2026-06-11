"use client"

import { useParams } from "next/navigation"
import { VBRSessionRecorder } from "./VBRSessionRecorder"

export default function Page() {
  const params = useParams<{ sessionId: string }>()
  const sessionId = Array.isArray(params.sessionId) ? params.sessionId[0] : params.sessionId

  if (!sessionId) return null

  return <VBRSessionRecorder sessionId={sessionId} />
}
