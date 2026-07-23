/**
 * Supabase Auth callback route.
 *
 * Handles the PKCE code exchange for magic-link logins.
 *
 * Flow:
 *  1. User clicks a Supabase magic-link email
 *  2. Supabase redirects to: <site>/auth/callback?code=<PKCE_CODE>&next=<path>
 *  3. This handler exchanges the code for a session (sets auth cookies)
 *  4. Redirects the user to `next` (default: /student)
 *
 * Supabase dashboard setup:
 *   Authentication → URL Configuration → Site URL = http://localhost:3000
 *   Authentication → URL Configuration → Redirect URLs → add:
 *     http://localhost:3000/auth/callback
 *
 * The primary OTP code flow (user types 6 digits) does NOT use this route;
 * it calls verifyOtp() directly in the browser. This route is the fallback
 * for users who click the link in the email instead of typing the code.
 */

import { createSupabaseServerClient } from "@/lib/supabase/server"
import { NextResponse } from "next/server"

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get("code")
  const next = searchParams.get("next") ?? "/student"
  const safeNext = next.startsWith("/") ? next : "/student"

  if (code) {
    const supabase = await createSupabaseServerClient()
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      return NextResponse.redirect(new URL(safeNext, origin))
    }
  }

  // Exchange failed or no code provided — send to login with an error hint
  return NextResponse.redirect(
    new URL("/login?error=auth_callback_error", origin)
  )
}
