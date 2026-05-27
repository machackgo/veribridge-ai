"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

// /admin redirects straight to the primary admin tool
export default function AdminRootPage() {
  const router = useRouter()
  useEffect(() => {
    router.replace("/admin/quality-review")
  }, [router])
  return null
}
