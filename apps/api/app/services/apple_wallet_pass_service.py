"""Apple Wallet Passport Pass — pass.json builder + gated .pkpass signing.

The Wallet pass is the third handoff surface for the Work Passport (after the
Beam Card and the printed/screenshotted QR), and it obeys the same two founding
rules as every other handoff surface:

1. **Public-safe by construction.** Every candidate-derived field on the pass
   comes from :func:`build_public_passport` — the SAME scrubbed, fail-closed
   public projection the recruiter sees at ``/p/{slug}``. The pass can never
   show something the public Passport does not show: no raw evidence, no
   transcripts, no storage paths, no signed URLs, no numeric scores, no
   internal ids. A final denylist scan (:func:`_assert_pass_json_safe`) refuses
   to serve any pass that trips it — defence in depth, mirroring the public
   passport's own ``enforce_public_safe`` gate.

2. **The QR is the existing revocable Beam short link.** The barcode message is
   ``{app}/b/{code}`` from :func:`create_or_reuse_beam_link` — the pass invents
   NO new sharing URL. Rotating or revoking the Beam link kills the QR inside
   every previously added Wallet pass at scan time, exactly like a printed
   card. This is why the pass needs no APNs update pipeline to stay safe (see
   docs/apple-wallet-pass-setup.md).

Feature gating (MVP-safe, never fakes Apple support):

- ``APPLE_WALLET_ENABLED=false`` (default) → the ``.pkpass`` endpoint answers
  a clear 404 "not enabled"; the availability endpoint reports disabled; the
  frontend renders no button.
- Flag on but identifiers / certificates missing → a clear 503 "not
  configured" — the endpoint NEVER returns an unsigned zip pretending to be a
  wallet pass.
- The dev-only ``pass-json`` preview works without any Apple material so the
  field mapping is testable end-to-end before certificates exist.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import struct
import zipfile
import zlib
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.beam_link_service import create_or_reuse_beam_link
from app.services.vbr_work_passport_service import build_public_passport

logger = logging.getLogger(__name__)

__all__ = [
    "apple_wallet_availability",
    "build_apple_pass_json",
    "build_signed_pkpass",
    "signing_files_present",
    "PKPASS_MEDIA_TYPE",
]

PKPASS_MEDIA_TYPE = "application/vnd.apple.pkpass"

# How many top proof-backed skills fit the pass face without truncating.
_MAX_PASS_SKILLS = 3

# Wallet pass card colors — deep VeriBridge navy with light text, matching the
# premium Beam Card identity (boarding-pass quality, not a toy).
_PASS_BACKGROUND_COLOR = "rgb(10, 14, 26)"
_PASS_FOREGROUND_COLOR = "rgb(255, 255, 255)"
_PASS_LABEL_COLOR = "rgb(154, 163, 178)"

# Markers that must NEVER appear anywhere in a serialized pass. The public
# passport payload is already scrubbed upstream; this is the belt to that
# braces, catching regressions in anything the pass builder adds on top.
_FORBIDDEN_PASS_MARKERS = (
    "supabase",
    "x-amz",
    "/object/sign/",
    "/users/",
    "file://",
    "storage_path",
    "access_token",
    "authorization",
    "transcript",
    "github_token",
)


# ── Availability (drives the frontend button and the .pkpass gate) ───────────


def signing_files_present() -> bool:
    """True only when all three configured signing files actually exist."""
    paths = (
        settings.apple_wallet_cert_path.strip(),
        settings.apple_wallet_key_path.strip(),
        settings.apple_wallet_wwdr_cert_path.strip(),
    )
    return all(path and os.path.isfile(path) for path in paths)


def apple_wallet_availability() -> dict[str, Any]:
    """Owner-facing readiness summary — booleans ONLY, never paths or values.

    ``enabled`` is the single source of truth the frontend button obeys: it is
    true only when the feature flag is on AND the pass identifiers are set AND
    every signing file is present, i.e. only when the ``.pkpass`` endpoint can
    actually produce a real signed pass.
    """
    feature_flag = bool(settings.apple_wallet_enabled)
    identifiers = settings.apple_wallet_identifiers_configured
    signing_ready = settings.apple_wallet_signing_paths_configured and signing_files_present()
    return {
        "enabled": feature_flag and identifiers and signing_ready,
        "feature_flag": feature_flag,
        "identifiers_configured": identifiers,
        "signing_ready": signing_ready,
    }


# ── pass.json builder (certificate-free, fully testable) ─────────────────────


def _absolute_app_url(path: str) -> str:
    """Absolute public web-app URL for a public path (e.g. ``/b/{code}``)."""
    base = (settings.public_app_url or settings.frontend_url or "").strip().rstrip("/")
    return f"{base}{path}" if base else path


def _stable_serial_number(user_id: str) -> str:
    """Stable, non-reversible serial per user — re-adding the pass replaces the
    old one instead of duplicating it, and no internal id rides on the pass."""
    digest = hashlib.sha256(f"veribridge-apple-wallet-pass:{user_id}".encode()).hexdigest()
    return f"vbr-{digest[:32]}"


def _iso_8859_1_safe(value: str) -> str:
    """Coerce a string to the barcode's iso-8859-1 message encoding, dropping
    anything unencodable (Beam URLs are pure ASCII, so this is a no-op guard)."""
    return value.encode("iso-8859-1", errors="ignore").decode("iso-8859-1")


def _count_label(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def build_apple_pass_json(db: Any, pipeline_db: Any, user_id: str) -> dict[str, Any]:
    """Build the Wallet ``pass.json`` for the caller's PUBLISHED passport.

    Requires no certificates, so the mapping is testable everywhere. Reuses the
    caller's active Beam short link (minting one exactly like the Beam Card
    does) and the public passport projection — raising the same 409 the Beam
    Card raises when the passport is not published.
    """
    # The Beam link service enforces the published-passport rule and returns
    # the ONE short link every handoff surface shares.
    link = create_or_reuse_beam_link(db, user_id)
    slug = link["public_passport_path"].removeprefix("/p/")

    # The recruiter-safe public projection — already scrubbed + safety-gated.
    public = build_public_passport(db, pipeline_db, slug)
    identity = public.get("identity") or {}

    short_url = _iso_8859_1_safe(_absolute_app_url(link["short_path"]))

    display_name = str(identity.get("display_name") or "Verified candidate profile")
    headline = str(identity.get("headline") or "Verified Work Passport")
    education = str(identity.get("education_summary") or "").strip()

    project_count = int(public.get("featured_project_count") or 0)
    top_skills = [
        str(s.get("skill") or "").strip()
        for s in (public.get("top_skills") or [])
        if str(s.get("skill") or "").strip()
    ][:_MAX_PASS_SKILLS]
    source_counts = public.get("evidence_source_counts") or {}
    proof_source_count = sum(1 for count in source_counts.values() if count)

    secondary_fields: list[dict[str, Any]] = [
        {"key": "role", "label": "ROLE", "value": headline},
    ]
    if education:
        secondary_fields.append({"key": "education", "label": "EDUCATION", "value": education})

    pass_json: dict[str, Any] = {
        "formatVersion": 1,
        "passTypeIdentifier": settings.apple_pass_type_identifier,
        "serialNumber": _stable_serial_number(user_id),
        "teamIdentifier": settings.apple_team_identifier,
        "organizationName": settings.apple_wallet_organization_name,
        "description": "VeriBridge Work Passport",
        "logoText": "VeriBridge",
        "backgroundColor": _PASS_BACKGROUND_COLOR,
        "foregroundColor": _PASS_FOREGROUND_COLOR,
        "labelColor": _PASS_LABEL_COLOR,
        "sharingProhibited": True,
        "generic": {
            "headerFields": [
                {
                    "key": "verified",
                    "label": "VERIFIED",
                    "value": _count_label(project_count, "PROJECT", "PROJECTS"),
                },
            ],
            "primaryFields": [
                {"key": "name", "label": "NAME", "value": display_name},
            ],
            "secondaryFields": secondary_fields,
            "auxiliaryFields": [
                {
                    "key": "top_skills",
                    "label": "TOP SKILLS",
                    "value": " · ".join(top_skills) if top_skills else "Building proof",
                },
                {
                    "key": "proof_sources",
                    "label": "PROOF SOURCES",
                    "value": _count_label(proof_source_count, "SOURCE", "SOURCES"),
                },
            ],
            "backFields": [
                {
                    "key": "about",
                    "label": "Public-safe proof summary",
                    "value": (
                        "This pass shows only the public-safe summary of a "
                        "verified VeriBridge Work Passport: real identity, "
                        "top proof-backed skills, and verified project counts. "
                        "Skill labels are qualitative — never numeric scores."
                    ),
                },
                {
                    "key": "privacy",
                    "label": "Private evidence protected",
                    "value": (
                        "Raw evidence — code, recordings, and documents — "
                        "never leaves VeriBridge and is never stored on this "
                        "pass. The QR opens a revocable link the candidate "
                        "can rotate or disable at any time."
                    ),
                },
                {
                    "key": "inspect",
                    "label": "Open the live public Passport to inspect proof",
                    "value": (
                        f"Scan the QR or visit {short_url} to open the live "
                        "public Passport, where every skill links to its "
                        "verified proof chain."
                    ),
                },
                {
                    "key": "public_link",
                    "label": "Public Passport link",
                    "value": short_url,
                },
            ],
        },
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": short_url,
                "messageEncoding": "iso-8859-1",
                "altText": short_url,
            },
        ],
    }

    _assert_pass_json_safe(pass_json, user_id=user_id, link_id=str(link.get("id") or ""))
    return pass_json


def _assert_pass_json_safe(pass_json: dict[str, Any], *, user_id: str, link_id: str) -> None:
    """Refuse to serve a pass that carries anything private. Fail closed."""
    serialized = json.dumps(pass_json).lower()
    leaks = [marker for marker in _FORBIDDEN_PASS_MARKERS if marker in serialized]
    if user_id and user_id.lower() in serialized:
        leaks.append("user id")
    if link_id and link_id.lower() in serialized:
        leaks.append("beam link id")
    if leaks:
        logger.warning("[AppleWallet] pass.json failed the safety scan; refusing to serve.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "apple_pass_unsafe",
                "message": "Wallet pass failed the public-safety scan and was not generated.",
            },
        )


# ── Signed .pkpass generation (feature-flag + certificate gated) ─────────────


def _not_enabled() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "apple_wallet_not_enabled",
            "message": "Apple Wallet passes are not enabled on this server.",
        },
    )


def _not_configured(message: str) -> HTTPException:
    """Config problems are 503 (server-side, transient-fixable) and NEVER echo
    paths or certificate material back to the caller."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "apple_wallet_not_configured", "message": message},
    )


def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Minimal valid solid-color PNG (placeholder pass art until designed
    VeriBridge icon assets are added — see the setup doc's asset checklist)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# Deep VeriBridge navy, matching the pass backgroundColor.
_ICON_RGB = (10, 14, 26)

# Directory of designed pass art (icon.png, icon@2x.png, logo.png, logo@2x.png).
# Optional: when absent, generated solid-navy placeholders keep the bundle
# valid — Wallet requires icon.png to exist in every pass.
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "apple_wallet")


def _pass_assets() -> dict[str, bytes]:
    """Collect pass art: designed files when present, placeholders otherwise."""
    assets: dict[str, bytes] = {}
    for name, size in (("icon.png", 29), ("icon@2x.png", 58), ("logo.png", 50), ("logo@2x.png", 100)):
        designed = os.path.join(_ASSETS_DIR, name)
        if os.path.isfile(designed):
            with open(designed, "rb") as fh:
                assets[name] = fh.read()
        else:
            assets[name] = _solid_png(size, size, _ICON_RGB)
    return assets


def _sign_manifest(manifest_bytes: bytes) -> bytes:
    """PKCS#7 detached signature over manifest.json with the Pass Type ID cert.

    Requires the optional ``cryptography`` package and the three PEM files from
    the Apple Developer setup. Every failure maps to a clear, path-free
    configuration error — this function never fakes a signature.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.serialization import pkcs7
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise _not_configured(
            "Apple Wallet signing requires the 'cryptography' package "
            "(pip install cryptography)."
        ) from exc

    try:
        with open(settings.apple_wallet_cert_path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
        with open(settings.apple_wallet_wwdr_cert_path, "rb") as fh:
            wwdr_cert = x509.load_pem_x509_certificate(fh.read())
        key_password = settings.apple_wallet_key_password.get_secret_value().encode() or None
        with open(settings.apple_wallet_key_path, "rb") as fh:
            private_key = serialization.load_pem_private_key(fh.read(), password=key_password)
    except HTTPException:
        raise
    except Exception as exc:
        # Unreadable/invalid PEM or wrong key password. Log server-side detail;
        # the response carries neither paths nor parser errors.
        logger.warning("[AppleWallet] Failed to load signing material: %s", type(exc).__name__)
        raise _not_configured(
            "Apple Wallet signing certificates could not be loaded. "
            "Check the certificate, key, and WWDR files and the key password."
        ) from exc

    try:
        return (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(manifest_bytes)
            .add_signer(cert, private_key, hashes.SHA256())
            .add_certificate(wwdr_cert)
            .sign(
                serialization.Encoding.DER,
                [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary],
            )
        )
    except Exception as exc:
        logger.warning("[AppleWallet] Pass signing failed: %s", type(exc).__name__)
        raise _not_configured(
            "Apple Wallet pass signing failed. Verify the Pass Type ID "
            "certificate matches the configured private key."
        ) from exc


def build_signed_pkpass(db: Any, pipeline_db: Any, user_id: str) -> bytes:
    """Produce a REAL signed ``.pkpass`` bundle, or fail with a clear error.

    Gate order (each failure mode is honest and distinct):
      1. feature flag off            → 404 ``apple_wallet_not_enabled``
      2. identifiers missing         → 503 ``apple_wallet_not_configured``
      3. signing files missing       → 503 ``apple_wallet_not_configured``
      4. pass.json build             → beam/passport rules apply (409 unpublished)
      5. manifest + PKCS#7 signature → real signature or a clear 503, never a
         fake/unsigned bundle
    """
    if not settings.apple_wallet_enabled:
        raise _not_enabled()
    if not settings.apple_wallet_identifiers_configured:
        raise _not_configured(
            "Apple Wallet is enabled but APPLE_PASS_TYPE_IDENTIFIER / "
            "APPLE_TEAM_IDENTIFIER are not set."
        )
    if not settings.apple_wallet_signing_paths_configured or not signing_files_present():
        raise _not_configured(
            "Apple Wallet is enabled but the signing certificate, private key, "
            "or WWDR certificate file is missing."
        )

    pass_json = build_apple_pass_json(db, pipeline_db, user_id)

    files: dict[str, bytes] = {
        "pass.json": json.dumps(pass_json, ensure_ascii=False, indent=2).encode("utf-8"),
        **_pass_assets(),
    }
    # Apple's manifest hashes every bundle file with SHA-1 (bundle integrity
    # format, unrelated to the signature hash, which is SHA-256).
    manifest = {
        name: hashlib.sha1(content).hexdigest()  # noqa: S324 - format mandated by Apple
        for name, content in files.items()
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    signature = _sign_manifest(manifest_bytes)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)
        bundle.writestr("manifest.json", manifest_bytes)
        bundle.writestr("signature", signature)

    logger.info("[AppleWallet] Signed .pkpass generated for user %s", user_id)
    return buffer.getvalue()
