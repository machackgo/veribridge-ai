# SMTP Domain Setup Status

VeriBridge AI currently keeps the real Supabase email OTP flow in place, but production-style email delivery through Resend custom SMTP is paused until the sending domain is verified.

## Current Issue

Resend failed to send the Supabase Auth verification email because the sender domain is not verified yet. The attempted sender used Resend's test setup, but `onboarding@resend.dev` is restricted and cannot send to arbitrary external recipients such as `mohammedmubashir@wpi.edu`.

This is expected provider behavior. We should not bypass Resend restrictions or use unverified sender identities for production authentication email.

## Why a Verified Domain Is Required

Authentication emails must come from a domain that the app controls. Resend requires DNS verification so it can prove the sender is authorized and can configure the required SPF, DKIM, and related deliverability records.

Until VeriBridge AI owns and verifies a sender domain, Supabase Auth may create OTP requests successfully but fail at the email delivery step.

## Planned Production Sender

- Future domain: `veribridgeai.com`
- Future auth sender: `auth@veribridgeai.com`

## Planned Supabase SMTP Values

Use these values in Supabase Auth SMTP settings after the domain and Resend sender are ready:

| Field | Value |
| --- | --- |
| Host | `smtp.resend.com` |
| Port | `465` |
| Username | `resend` |
| Password | Resend API key |
| Sender email | `auth@veribridgeai.com` |

Do not commit the Resend API key or any SMTP password to the repository.

## After Buying `veribridgeai.com`

1. Add `veribridgeai.com` in Resend.
2. Add the DNS records Resend provides.
3. Wait for Resend domain verification to pass.
4. Create or confirm the sender address `auth@veribridgeai.com`.
5. Update Supabase Auth SMTP settings with the verified sender email and Resend SMTP values.
6. Test `/login` with a real `.edu` address.
7. Confirm that the verification email is delivered and the OTP flow still redirects to the dashboard after verification.

