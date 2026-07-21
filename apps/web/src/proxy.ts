import { createServerClient } from "@supabase/ssr"
import { type NextRequest, NextResponse } from "next/server"

/**
 * Auth proxy for VeriBridge AI (Next.js 16 "proxy" convention).
 *
 * Protected paths: /dashboard/**, /onboarding, /student/**
 *
 * Behaviour:
 *  - Unauthenticated request to protected paths → redirect /login?next=<path>
 *  - Authenticated request to /login → redirect to requested next path or /student/vbr
 *  - All other paths → pass through unchanged
 *
 * Session check uses getSession() (reads JWT from cookie, no extra network
 * round-trip). The actual JWT is validated per-request by the backend API;
 * the proxy only decides whether to redirect the browser.
 *
 * DEMO_MODE bypass (server-only env var, never NEXT_PUBLIC_):
 *   Set DEMO_MODE=true to skip all auth redirects. Used by the Playwright
 *   test suite and local development without a real Supabase session.
 *   NEVER set this in production.
 */
export async function proxy(request: NextRequest) {
  // NEXT_PUBLIC_ prefix ensures this is baked into the Edge Runtime bundle
  // at build time (plain DEMO_MODE is not available in Edge Runtime).
  if (process.env.NEXT_PUBLIC_DEMO_MODE === "true") {
    return NextResponse.next()
  }

  const { pathname } = request.nextUrl

  // Paths that never require auth (add more as the app grows).
  // Tokenized/slug public share routes are gated by the token/slug itself and
  // by the backend (which only serves published, recruiter-safe projections),
  // so a recruiter must be able to open them while logged out:
  //   /vbr/report/<token> — published Verified Build Report
  //   /r/<token>          — legacy public report
  //   /p/<slug>[/skills/<skill>] — published public Work Passport + Skill Report
  const isPublic =
    pathname === "/" ||
    pathname === "/login" ||
    pathname.startsWith("/auth/") ||
    pathname.startsWith("/recruiter") ||
    pathname.startsWith("/university") ||
    pathname.startsWith("/r/") ||
    pathname.startsWith("/vbr/report/") ||
    pathname.startsWith("/p/")

  if (isPublic) {
    // If the user is already logged in, bounce them away from /login
    // so they don't see the login form while already authenticated.
    if (pathname === "/login") {
      const session = await getSessionSafe(request)
      if (session) {
        const next = request.nextUrl.searchParams.get("next") ?? "/student/vbr"
        const dest = request.nextUrl.clone()
        dest.pathname = next.startsWith("/") ? next : "/dashboard"
        dest.search = ""
        return NextResponse.redirect(dest)
      }
    }
    return NextResponse.next()
  }

  // For all other paths (dashboard and first-run onboarding) check for a session.
  // Build a response object we can attach refreshed auth cookies to.
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
          // Mirror refreshed tokens to both the request and the response
          // so the browser and any downstream server component stay in sync.
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

  // getSession() reads the JWT from the auth cookie and validates its
  // signature locally — no round-trip to Supabase per request.
  // Expired tokens are refreshed via the refresh_token (one network call).
  const {
    data: { session },
  } = await supabase.auth.getSession()

  if (!session) {
    const loginUrl = request.nextUrl.clone()
    loginUrl.pathname = "/login"
    loginUrl.search = ""
    loginUrl.searchParams.set("next", pathname)
    return NextResponse.redirect(loginUrl)
  }

  return supabaseResponse
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function getSessionSafe(request: NextRequest) {
  try {
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return request.cookies.getAll()
          },
          setAll() {
            // Read-only check — no cookie updates needed here
          },
        },
      }
    )
    const { data } = await supabase.auth.getSession()
    return data.session
  } catch {
    return null
  }
}

export const config = {
  matcher: [
    /*
     * Run on all paths except Next.js internals and static files.
     * Auth logic in the function body decides which paths are gated.
     */
    "/((?!_next/static|_next/image|favicon.ico|api/).*)",
  ],
}
