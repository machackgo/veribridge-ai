# Apple Wallet Passport Pass — Developer Setup

This guide covers everything required to turn on **"Add to Apple Wallet"** for
the VeriBridge Work Passport. The code foundation (pass.json builder, gated
endpoints, feature flag, frontend button) ships in this repo and works without
any Apple material; **issuing a real signed `.pkpass` requires the Apple
Developer setup below.**

Until that setup is complete, keep `APPLE_WALLET_ENABLED=false` (the default).
The product then makes **no Apple Wallet claim anywhere**: the `.pkpass`
endpoint answers a clear "not enabled" 404, the readiness endpoint reports
disabled, and `/beam` renders no wallet button.

---

## 1. What you need from Apple

### 1.1 Apple Developer Program membership (required, paid)

Wallet passes can only be signed with a certificate issued through the
[Apple Developer Program](https://developer.apple.com/programs/) (USD 99/year).
There is no free-tier or personal-team path for pass signing. The membership
gives you the **Team ID** (10 characters, e.g. `A1B2C3D4E5`) shown on the
[Membership page](https://developer.apple.com/account#MembershipDetailsCard)
— that value becomes `APPLE_TEAM_IDENTIFIER`.

### 1.2 Pass Type ID

1. Developer portal → **Certificates, Identifiers & Profiles → Identifiers**.
2. Register a new identifier of type **Pass Type IDs**.
3. Use a reverse-DNS id, e.g. `pass.com.veribridgeai.passport`.
4. That exact string becomes `APPLE_PASS_TYPE_IDENTIFIER` and must match the
   `passTypeIdentifier` baked into every pass — Wallet rejects a pass whose
   signature certificate does not match its `passTypeIdentifier`.

### 1.3 Pass Type ID certificate

1. In the portal, open the Pass Type ID → **Create Certificate**.
2. Create a CSR locally (Keychain Access → Certificate Assistant → *Request a
   Certificate From a Certificate Authority*, saved to disk), upload it, and
   download the issued `pass.cer`.
3. Import `pass.cer` into your login keychain (double-click). It pairs with
   the private key that generated the CSR.

### 1.4 WWDR intermediate certificate (G4)

The signature must include Apple's **Worldwide Developer Relations**
intermediate certificate. Pass Type ID certificates issued today chain to
**WWDR G4** — download `AppleWWDRCAG4.cer` from
[Apple PKI](https://www.apple.com/certificateauthority/). If Wallet silently
refuses your pass, a G-series mismatch (G4 cert signed with a G1/G3 chain) is
the most common cause; check the issuer of your pass certificate and ship the
matching WWDR file.

---

## 2. Exporting and converting the signing material

### 2.1 `.p12` export

In Keychain Access, expand your imported **Pass Type ID certificate** so the
paired private key shows, select both, right-click → **Export 2 items…** →
`.p12`. Choose a strong export password — it becomes
`APPLE_WALLET_KEY_PASSWORD` (or can be stripped in the next step).

### 2.2 PEM conversion (what the backend consumes)

The backend loads three **PEM** files:

```bash
# 1. Signing certificate (public part of the Pass Type ID cert)
openssl pkcs12 -in passkit.p12 -clcerts -nokeys -legacy -out pass-cert.pem

# 2. Private key. Keep it encrypted (recommended) …
openssl pkcs12 -in passkit.p12 -nocerts -legacy -out pass-key.pem
#    … then set APPLE_WALLET_KEY_PASSWORD to the passphrase you chose.
#    (Add -nodes instead to strip the passphrase; then leave the password empty
#    and rely entirely on filesystem/secret-mount permissions.)

# 3. WWDR G4 intermediate (DER → PEM)
openssl x509 -inform der -in AppleWWDRCAG4.cer -out wwdr-g4.pem
```

> `-legacy` is needed with OpenSSL 3.x because Keychain exports use RC2-based
> PKCS#12 encryption that OpenSSL 3 moved to the legacy provider.

### 2.3 Where the files live

**Never commit these files.** Put them outside the repo (or in a git-ignored
secrets dir), and in production mount them as **secret files** (Render secret
files, Kubernetes secret volume, etc.). The env vars carry **paths only** —
never certificate contents, never a base64 blob in an env var.

---

## 3. Required environment variables

All placeholders are in `apps/api/.env.example`:

| Variable | Meaning | Example |
| --- | --- | --- |
| `APPLE_WALLET_ENABLED` | Master feature flag. Default `false`. | `true` |
| `APPLE_PASS_TYPE_IDENTIFIER` | Registered Pass Type ID | `pass.com.veribridgeai.passport` |
| `APPLE_TEAM_IDENTIFIER` | 10-char Team ID | `A1B2C3D4E5` |
| `APPLE_WALLET_ORGANIZATION_NAME` | `organizationName` on the pass | `VeriBridge AI` |
| `APPLE_WALLET_CERT_PATH` | Path/secret-file ref to `pass-cert.pem` | `/etc/secrets/pass-cert.pem` |
| `APPLE_WALLET_KEY_PATH` | Path/secret-file ref to `pass-key.pem` | `/etc/secrets/pass-key.pem` |
| `APPLE_WALLET_WWDR_CERT_PATH` | Path/secret-file ref to `wwdr-g4.pem` | `/etc/secrets/wwdr-g4.pem` |
| `APPLE_WALLET_KEY_PASSWORD` | Key passphrase (empty if key is unencrypted) | *(secret)* |

Plus one optional Python dependency (see `requirements.txt`):

```bash
pip install "cryptography>=42.0.0"   # PKCS#7 detached signing
```

Everything except actual `.pkpass` signing — the pass.json builder, the dev
preview endpoint, all tests — works without this package and without any of
the variables above.

### Readiness model

`GET /api/v1/student/vbr/wallet/apple/availability` reports `enabled: true`
**only** when the flag is on AND both identifiers are set AND all three PEM
files actually exist on disk. The `/beam` button obeys that flag, so a
misconfigured server can never show a button that would fail.

---

## 4. Endpoints (all owner-auth)

| Endpoint | Purpose | Gate |
| --- | --- | --- |
| `GET …/wallet/apple/availability` | Readiness booleans for the UI | none (always answers honestly) |
| `GET …/wallet/apple/pass-json` | Dev/test preview of the pass.json mapping, no certs needed | flag on **or** non-production env |
| `GET …/wallet/apple/pass.pkpass` | Real signed pass, `application/vnd.apple.pkpass` | flag on **and** identifiers **and** cert files, else clear 404/503 |

The `.pkpass` endpoint **never** returns an unsigned bundle: with the flag off
it 404s (`apple_wallet_not_enabled`); with signing material missing/broken it
503s (`apple_wallet_not_configured`) without echoing paths.

---

## 5. Why `/b/{code}` remains the source of truth

The pass barcode encodes the student's existing **revocable Beam short link**
(`{app}/b/{code}`) — the same link the Beam Card QR uses — not a direct
`/p/{slug}` URL and not a new wallet-specific URL. This is deliberate:

- **Revocation without APNs.** A Wallet pass, once added, lives on the
  recruiter's/student's device; VeriBridge cannot edit it without the full
  APNs pass-update pipeline (§6). But because the QR resolves **server-side at
  scan time**, rotating or revoking the Beam link instantly kills the QR in
  every pass ever added — same guarantee as a printed card.
- **One sharing surface.** Beam Card, printed QR, and Wallet pass all carry
  the same short link, so the audit trail, revocation UI, and passport
  publish/unpublish semantics apply uniformly. The pass invents no parallel
  sharing URL.
- **No identity in the code.** Beam codes are ~96-bit random tokens; an
  invalid/revoked scan returns one generic "inactive" answer with zero holder
  data.

## 6. APNs / pass-update limitation (accepted for MVP)

Full Wallet integration lets a pass update itself (webServiceURL +
authenticationToken in pass.json, device registration endpoints, and APNs
pushes). **This MVP intentionally ships without it.** Consequences:

- Fields on an added pass (name, skills, counts) are a **snapshot** — they
  refresh only if the student re-downloads the pass (same stable
  `serialNumber`, so re-adding replaces rather than duplicates).
- Because the QR resolves live via `/b/{code}`, **safety never depends on
  updating the pass** — stale cosmetics at worst, never stale access.
- When pass updates are wanted later: implement Apple's PassKit Web Service
  spec (register/unregister device endpoints, serial-based updates), add an
  APNs pass-type certificate, and add `webServiceURL`/`authenticationToken`
  to the pass — a separate, deliberate project.

## 7. Local development limitation

- Without Apple material, use `GET …/wallet/apple/pass-json` to verify field
  mapping; the `.pkpass` endpoint will honestly 404/503.
- A signed pass can be produced locally once the three PEM files exist and the
  env vars point at them — but **iOS only installs passes signed by a real
  Apple-issued Pass Type ID certificate**. Self-signed material is useless for
  end-to-end testing; expect to test with the real (or a staging) certificate.
- The generated pass currently uses placeholder solid-navy `icon.png` /
  `logo.png` art. Before launch, drop designed assets into
  `apps/api/app/assets/apple_wallet/` (`icon.png` 29×29, `icon@2x.png` 58×58,
  `logo.png` ≤160×50 @1x, `logo@2x.png`) — designed files are picked up
  automatically and placeholders are only a fallback.
- The simulator can preview `.pkpass` files (drag onto Simulator → Wallet);
  a physical iPhone is the real test.

## 8. Security warnings

- **NEVER commit** `.p12`, `.pem`, `.cer` files, or the key password. Keep
  them out of the repo entirely; use secret file mounts in production.
- **Never put certificate contents in env vars** — paths/secret refs only.
- The pass face and back fields carry **public-safe data only** (the same
  scrubbed projection as the public Passport): no raw evidence, no
  transcripts, no storage paths, no signed URLs, no internal ids, no numeric
  scores. The builder refuses to emit a pass that trips its safety scan.
- The key password lives in `APPLE_WALLET_KEY_PASSWORD` as a `SecretStr` and
  is never logged or echoed in error responses.
