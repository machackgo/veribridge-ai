import { createServerClient } from "@supabase/ssr"
import { type NextRequest, NextResponse } from "next/server"

/**
 * Auth proxy for VeriBridge AI (Next.js 16 "proxy" convention).
 *
 * Protected paths: /dashboard/**, /onboarding, /student/**
 *
 * Behaviour:
 *  - Unauthenticated request to protected paths → redirect /login?next=<path>
 *  - Authenticated request to /login → redirect to requested next path or /student
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
  // HARD production guard: the demo bypass disables ALL auth redirects, so a
  // mis-set Vercel env var must never be able to open the app in production.
  const demoBypass =
    process.env.NEXT_PUBLIC_DEMO_MODE === "true" &&
    process.env.VERCEL_ENV !== "production" &&
    process.env.NODE_ENV !== "production"
  if (demoBypass) {
    return NextResponse.next()
  }

  const { pathname } = request.nextUrl

  // /dev/* pages are local development previews built on fabricated sample
  // data (fake candidates, invented review labels). They must never render in
  // production — a recruiter or student reaching one would see invented
  // "verified" evidence with no sample banner.
  if (
    (pathname === "/dev" || pathname.startsWith("/dev/")) &&
    (process.env.VERCEL_ENV === "production" || process.env.NODE_ENV === "production")
  ) {
    return new NextResponse(null, { status: 404 })
  }

  // Paths that never require auth (add more as the app grows).
  // Tokenized/slug public share routes are gated by the token/slug itself and
  // by the backend (which only serves published, recruiter-safe projections),
  // so a recruiter must be able to open them while logged out:
  //   /vbr/report/<token> — published Verified Build Report
  //   /r/<token>          — legacy public report
  //   /p/<slug>[/skills/<skill>] — published public Work Passport + Skill Report
  //   /card/<slug>        — public Passport Card (subset of /p data)
  //   /b/<code>           — revocable Beam short link (fail-closed resolver)
  //   /extension/**       — recorder install help / privacy policy / support
  //                         (must stay public: they are the Chrome Web Store
  //                         listing's privacy-policy and support URLs)
  //   /privacy            — canonical VeriBridge privacy policy (Chrome Web
  //                         Store requires it reachable without login)
  const isPublic =
    pathname === "/" ||
    pathname === "/login" ||
    pathname === "/privacy" ||
    pathname === "/robots.txt" ||
    pathname === "/sitemap.xml" ||
    pathname === "/icon.svg" ||
    pathname === "/apple-icon.png" ||
    // Static Keystone V brand assets (favicon/social/og images)
    pathname.startsWith("/brand/") ||
    // Static marketing media (launch film + poster) served from the Vercel
    // CDN. MUST stay public: the proxy matcher runs on /media/* (only
    // _next/static, _next/image, favicon.ico and api/ are excluded), so
    // without this entry the landing-page <video> src would 307 to /login
    // and the film would never play for a logged-out visitor.
    pathname.startsWith("/media/") ||
    pathname === "/extension" ||
    pathname.startsWith("/extension/") ||
    pathname.startsWith("/auth/") ||
    pathname.startsWith("/recruiter") ||
    pathname.startsWith("/university") ||
    pathname.startsWith("/r/") ||
    pathname.startsWith("/vbr/report/") ||
    pathname.startsWith("/p/") ||
    pathname.startsWith("/card/") ||
    pathname.startsWith("/b/")

  if (isPublic) {
    // If the user is already logged in, bounce them away from /login
    // so they don't see the login form while already authenticated.
    if (pathname === "/login") {
      const session = await getSessionSafe(request)
      if (session) {
        const next = request.nextUrl.searchParams.get("next") ?? "/student"
        const dest = request.nextUrl.clone()
        // Same-origin paths only — reject protocol-relative "//host" values.
        dest.pathname =
          next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")
            ? next
            : "/dashboard"
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
