"""Shared backend test configuration.

Global, autouse hermeticity guard for the LLM Synthesis Layer (Step 4).

The synthesis layer (:mod:`app.services.llm_proof_synthesis_service`) can, when
enabled, call a real LLM provider — a local OpenAI-compatible server
(Ollama / vLLM / LM Studio) over ``httpx``, or the Anthropic API. A developer
``.env`` with ``LLM_SYNTHESIS_ENABLED=true`` (and a base URL / API key) would
otherwise let ANY backend test that exercises the *production* synthesis path —
the proof-synthesis agent, VBR student reports, the work passport, etc. — make a
real network call to a live provider. That is exactly the leak Codex flagged:
hermeticity was only enforced inside ``test_llm_proof_synthesis_service.py``.

This autouse fixture makes the WHOLE backend test suite hermetic by default:

1. It forces the synthesis layer OFF and the provider to ``disabled`` at the
   settings level, so :func:`app.services.llm_proof_synthesis_service._resolve_llm_fn`
   returns ``None`` on every production path regardless of the developer's
   ``.env``.
2. Defense in depth: it neutralises the two provider builders
   (``_local_openai_llm_fn`` / ``_anthropic_llm_fn``) so that even if a test or a
   leaked env flips the layer on, the synthesis path resolves to the deterministic
   fallback and never constructs an httpx client or an Anthropic client — no real
   network call can escape the synthesis provider path.

It is intentionally scoped to the synthesis provider path ONLY: it does NOT touch
``httpx.Client`` globally, because FastAPI's ``TestClient`` subclasses
``httpx.Client`` and many backend services construct ``httpx.Client`` directly —
blocking it globally would break those suites. Each provider builder is the single
choke point through which the synthesis layer reaches the network, so neutralising
just those two is sufficient and surgical.

Tests that intentionally exercise a provider opt back in explicitly (see
``_enable_local`` and ``test_anthropic_is_optional_and_not_default`` in
``test_llm_proof_synthesis_service.py``): they restore the real builder and install
a FAKE httpx client / unconfigured creds, so they remain fully hermetic and never
perform a real call.
"""

from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _hermetic_llm_synthesis(monkeypatch):
    """Force the LLM synthesis layer offline for every backend test.

    Autouse + module-shared so no suite can accidentally reach a real provider when
    a developer ``.env`` enables synthesis. Provider tests override this explicitly.
    """
    # 1. Layer OFF regardless of developer .env → _resolve_llm_fn() returns None on
    #    every production synthesis path.
    monkeypatch.setattr(settings, "llm_synthesis_enabled", False, raising=False)
    monkeypatch.setattr(settings, "llm_synthesis_provider", "disabled", raising=False)

    # 2. Defense in depth: even a force-enabled layer cannot reach a real provider.
    #    Both builders are the only places the synthesis layer touches the network;
    #    returning None makes the layer fail closed to its deterministic fallback
    #    without ever constructing an httpx/Anthropic client. (Scoped to this module
    #    only — httpx.Client itself is left untouched for TestClient & other suites.)
    import app.services.llm_proof_synthesis_service as llm_mod

    def _blocked_provider(*_args, **_kwargs):
        return None

    monkeypatch.setattr(llm_mod, "_local_openai_llm_fn", _blocked_provider, raising=False)
    monkeypatch.setattr(llm_mod, "_anthropic_llm_fn", _blocked_provider, raising=False)
    yield
