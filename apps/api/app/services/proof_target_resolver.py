"""Proof target URL/domain resolver.

Resolves the canonical target website URL and domain for a Website Proof session.

Lookup order:
  1. extension_proof_sessions.website_url (session-level column)
  2. proof_data.live_website_check.website_url
  3. proof_data.website_url or proof_data.submitted_url

All results are normalized: protocol stripped, www. stripped, fragments dropped.
"""

from __future__ import annotations

from urllib.parse import urlparse


def resolve_target_url(
    session_website_url: str | None,
    proof_data: dict,
) -> str | None:
    """Return the canonical target website URL for a proof session.

    Checks session-level website_url first, then falls back to proof_data.
    Returns None when no URL can be resolved.
    """
    if session_website_url and session_website_url.strip():
        return session_website_url.strip()
    if isinstance(proof_data, dict):
        lw = proof_data.get("live_website_check") or {}
        if isinstance(lw, dict) and lw.get("website_url"):
            return str(lw["website_url"]).strip()
        if proof_data.get("website_url"):
            return str(proof_data["website_url"]).strip()
        if proof_data.get("submitted_url"):
            return str(proof_data["submitted_url"]).strip()
    return None


def resolve_target_domain(
    session_website_url: str | None,
    proof_data: dict,
) -> str | None:
    """Return the bare target domain for a proof session (e.g. 'threejs.org').

    Strips protocol, www. prefix, paths, and fragments.
    Returns None when no URL can be resolved.
    """
    url = resolve_target_url(session_website_url, proof_data)
    if not url:
        return None
    return normalize_domain(url)


def normalize_domain(url: str) -> str | None:
    """Extract bare domain from a URL string.

    Handles:
    - URLs with or without scheme (adds https:// if missing)
    - www. prefix removal
    - path / fragment stripping
    - host:port (port retained so localhost:3000 is distinct from localhost:5000)

    Examples:
        'https://threejs.org/examples/#webgl' -> 'threejs.org'
        'www.github.com/mrdoob/three.js'     -> 'github.com'
        'localhost:3000'                      -> 'localhost:3000'
    """
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or None
    except Exception:
        return None


def domain_matches_target(row_domain: str, target_domain: str) -> bool:
    """Return True when row_domain is the target domain or a subdomain of it.

    Strips www. from both sides before comparison.

    Examples:
        domain_matches_target('threejs.org', 'threejs.org')         -> True
        domain_matches_target('examples.threejs.org', 'threejs.org')-> True
        domain_matches_target('supabase.com', 'threejs.org')        -> False
        domain_matches_target('github.com', 'github.com')           -> True
    """
    row = (row_domain or "").lower().strip()
    tgt = (target_domain or "").lower().strip()
    if row.startswith("www."):
        row = row[4:]
    if tgt.startswith("www."):
        tgt = tgt[4:]
    if not row or not tgt:
        return False
    return row == tgt or row.endswith("." + tgt)
