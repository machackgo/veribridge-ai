import { createServerClient } from "@supabase/ssr"
import { type NextRequest, NextResponse } from "next/server"

/**
 * Auth middleware for VeriBridge AI.
 *
 * Protected paths: /dashboard/**
 *
 * DEMO_MODE bypass (server-only env var, not NEXT_PUBLIC_):
 *   Set DEMO_MODE=true to skip auth checks — used by the Playwright
 *   test suite and local development without a real Supabase session.
 *   Never set this in production.
 */
export async function proxy(request: NextRequest) {
  if (process.env.DEMO_MODE === "true") {
    return NextResponse.next()
  }

  const { pathname } = request.nextUrl

  // Only protect /dashboard/* for now.
  // /recruiter/* and /university/* remain prototype-accessible.
  if (!pathname.startsWith("/dashboard")) {
    return NextResponse.next()
  }

  // Build a response we can attach refreshed auth cookies to.
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          // Mirror cookies to both the outgoing request and the response
          // so the browser and the server stay in sync.
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          )
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  // Use getUser() (not getSession()) — only getUser() validates the JWT
  // with Supabase Auth servers, making it safe for server-side checks.
  const {
    data: { user },
  } = await supabase.auth.getUser()

  if (!user) {
    const loginUrl = request.nextUrl.clone()
    loginUrl.pathname = "/login"
    loginUrl.searchParams.set("next", pathname)
    return NextResponse.redirect(loginUrl)
  }

  return supabaseResponse
}

export const config = {
  matcher: [
    /*
     * Run on all paths except Next.js internals and static files.
     * The middleware itself gates only /dashboard/* — the matcher
     * is broad so we can later extend protection without touching config.
     */
    "/((?!_next/static|_next/image|favicon.ico|api/).*)",
  ],
}
