# Local Auth Testing

The real VeriBridge AI authentication flow uses Supabase Auth email OTP. That flow should stay in place for production and for final integration testing.

While Resend SMTP is paused pending a verified sender domain, use demo mode for local frontend development.

## Enable Demo Mode

In `apps/web/.env.local`, set:

```bash
NEXT_PUBLIC_DEMO_MODE=true
```

Then restart the frontend dev server:

```bash
npm --prefix apps/web run dev
```

With demo mode enabled, dashboard routes are accessible for development without a real Supabase session. This keeps frontend work moving while SMTP/domain setup is incomplete.

## What Demo Mode Does Not Replace

Demo mode does not remove or replace:

- `/login`
- `/auth/callback`
- Supabase OTP sending and verification
- Backend JWT verification
- Protected route logic

Real OTP auth can be tested again after `veribridgeai.com` is purchased, verified in Resend, and configured as the Supabase SMTP sender domain.

