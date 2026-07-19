from functools import lru_cache
from urllib.parse import urlparse

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App identity ──────────────────────────────────────────────
    app_name: str = Field(default="careerproof-api", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # ── CORS ─────────────────────────────────────────────────────
    # Comma-separated list of allowed frontend origins.
    # Canonical env var is CORS_ALLOWED_ORIGINS; the older CORS_ORIGINS is
    # still accepted for backward compatibility (CORS_ALLOWED_ORIGINS wins).
    # Production example:
    #   https://veribridgeai.com,https://www.veribridgeai.com,http://localhost:3000,http://127.0.0.1:3000
    # A literal "*" wildcard origin is rejected when ENVIRONMENT=production
    # (see _reject_wildcard_cors_in_production below).
    cors_origins_raw: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("CORS_ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )

    # ── Public URLs (production domain integration) ──────────────
    # Canonical public origins for veribridgeai.com. These document the
    # deployment and are available for building absolute links; they do NOT
    # widen CORS by themselves — CORS is driven solely by the list above.
    #   FRONTEND_URL / PUBLIC_APP_URL → the web app,  e.g. https://veribridgeai.com
    #   BACKEND_PUBLIC_URL            → the public API, e.g. https://api.veribridgeai.com
    frontend_url: str = Field(
        default="http://localhost:3000", alias="FRONTEND_URL"
    )
    public_app_url: str = Field(
        default="http://localhost:3000", alias="PUBLIC_APP_URL"
    )
    backend_public_url: str = Field(
        default="http://localhost:8000", alias="BACKEND_PUBLIC_URL"
    )

    # ── Supabase ─────────────────────────────────────────────────
    # SUPABASE_URL is the project REST/API base URL, e.g.
    # https://<project-ref>.supabase.co
    # It is NOT the Postgres DATABASE_URL — they are different things.
    supabase_url: str = Field(default="", alias="SUPABASE_URL")

    supabase_anon_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_ANON_KEY"
    )

    # Server-side only — bypasses RLS.  Never expose to a browser.
    supabase_service_role_key: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_SERVICE_ROLE_KEY"
    )

    # ── Auth ──────────────────────────────────────────────────────
    # SUPABASE_JWT_SECRET is the LEGACY HS256 signing secret (Supabase
    # dashboard → Settings → API → JWT Settings → JWT Secret). Projects on the
    # newer asymmetric "JWT signing keys" (ES256/RS256) don't need it — those
    # tokens are verified against the public JWKS derived from SUPABASE_URL
    # (see ``supabase_jwks_url``). A token that can't be verified by either
    # scheme always fails closed with 401.
    supabase_jwt_secret: SecretStr = Field(
        default=SecretStr(""), alias="SUPABASE_JWT_SECRET"
    )

    # ── Demo / development overrides ─────────────────────────────
    # Fallback user ID used when no Authorization header is present
    # and ENVIRONMENT != "production".  Set to the real auth user UUID
    # created by scripts/create_demo_auth_user.py.
    demo_user_id: str = Field(
        default="00000000-0000-0000-0000-000000000001",
        alias="DEMO_USER_ID",
    )

    # SECURITY: the DEMO_USER_ID fallback impersonates a *real*, data-bearing
    # user. It must NEVER be reachable by an unauthenticated caller in normal
    # operation, or every logged-out/failed-auth request silently reads (and
    # can write) that user's private proof data — a cross-tenant data leak.
    #
    # Therefore the fallback is OFF by default and only ever applies when:
    #   • ENVIRONMENT != "production", AND
    #   • ENABLE_DEMO_USER_FALLBACK=true is explicitly set, AND
    #   • the request carries NO Authorization header at all.
    #
    # A *present* token that fails verification (bad signature, expired,
    # missing SUPABASE_JWT_SECRET) always yields 401 — it is never silently
    # downgraded to the demo user. Enable this only for throwaway local curl /
    # Swagger poking, ideally pointing DEMO_USER_ID at a disposable account.
    enable_demo_user_fallback: bool = Field(
        default=False,
        alias="ENABLE_DEMO_USER_FALLBACK",
    )

    # ── Database (direct Postgres connection) ────────────────────
    # Used by async SQLAlchemy — NOT the same as SUPABASE_URL.
    database_url: SecretStr = Field(
        default=SecretStr(""), alias="DATABASE_URL"
    )

    # ── GitHub API ────────────────────────────────────────────────
    # Optional personal access token for portfolio scanning.
    # Without it GitHub enforces 60 unauthenticated req/hr.
    # With it the limit rises to 5,000 req/hr.
    # Required scopes: public_repo (read access to public repositories).
    github_token: SecretStr | None = Field(default=None, alias="GITHUB_TOKEN")

    # ── Project Defense media storage ─────────────────────────────
    # Name of the Supabase Storage bucket for uploaded defense media files.
    # Leave empty to disable storage (students must paste transcripts manually).
    # Example: project-defense-media
    supabase_defense_media_bucket: str = Field(
        default="",
        alias="SUPABASE_DEFENSE_MEDIA_BUCKET",
    )

    # ── Keyframe / visual frame evidence storage ──────────────────
    # Name of the Supabase Storage bucket for extracted keyframe JPEGs.
    # When empty, keyframes are analyzed in-memory only (no persistent screenshots).
    # When set, each extracted JPEG + a thumbnail are uploaded and
    # frame_storage_path / frame_thumbnail_storage_path are persisted in DB.
    # Example: frame-evidence
    supabase_frame_evidence_bucket: str = Field(
        default="",
        alias="SUPABASE_FRAME_EVIDENCE_BUCKET",
    )

    # ── VBR session recording storage ──────────────────────────────
    # Name of the (private) Supabase Storage bucket for verified build
    # report (VBR) session video chunks. When empty, chunk-upload-url
    # falls back to a clearly-marked placeholder (see
    # vbr_session_recording.create_chunk_upload_target).
    # Example: vbr-media
    supabase_vbr_media_bucket: str = Field(
        default="",
        alias="SUPABASE_VBR_MEDIA_BUCKET",
    )

    # ── Passport Card profile photo storage ───────────────────────
    # Name of the PUBLIC Supabase Storage bucket that holds recruiter-safe
    # Passport Card profile photos (see migration 054). Objects live under a
    # per-user `<user_id>/…` prefix and are served via a plain public URL — no
    # signed URLs. When empty, profile-photo upload is disabled and the card
    # falls back to safe initials.
    # Example: passport-avatars
    supabase_passport_avatar_bucket: str = Field(
        default="",
        alias="SUPABASE_PASSPORT_AVATAR_BUCKET",
    )

    # ── Proof artifact retention storage ──────────────────────────
    # Name of the PRIVATE Supabase Storage bucket for retained original proof
    # artifacts (document originals, video proof originals/frames, website
    # replay videos — see migration 056). Paths are server-side only; access
    # flows through /api/v1/proofs/artifacts/* gated routes. When empty,
    # artifact retention is disabled: uploads that would retain bytes degrade
    # honestly (documents fall back to verified-excerpts-only; video proof
    # upload returns 503).
    # Example: proof-artifacts
    supabase_proof_artifact_bucket: str = Field(
        default="",
        alias="SUPABASE_PROOF_ARTIFACT_BUCKET",
    )

    # ── AI Domain Reviewer ────────────────────────────────────────
    # Anthropic API key for AI Domain Reviewer agents (Astra, Atlas, Nova, etc.)
    #
    # When ANTHROPIC_API_KEY is absent (or empty), the domain reviewer service
    # falls back to deterministic rubric-based scoring automatically.
    # No exceptions are raised — the response includes a clear note:
    #   "LLM reviewer not configured; using rubric-based deterministic review."
    #
    # This means local development and all tests work without any Anthropic config.
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="ANTHROPIC_API_KEY",
    )

    # Model used for AI domain reviewer agents.
    #
    # Leave empty (default) to use the deterministic fallback.
    # In production, set AI_REVIEWER_MODEL to a real Anthropic model ID
    # (e.g. "claude-sonnet-4-6" or "claude-opus-4-7").
    # Do NOT hardcode a model name here — configure it per environment via .env.
    #
    # The service validates that this is non-empty AND that ANTHROPIC_API_KEY is
    # set before attempting any LLM call.  If either is missing, the deterministic
    # fallback is used and the review result notes the reason.
    ai_reviewer_model: str = Field(
        default="",
        alias="AI_REVIEWER_MODEL",
    )

    # ── Transcription ─────────────────────────────────────────────
    # Which transcription provider to use for project defense audio/video.
    # Values: none | openai | local_whisper   (default: none)
    # none          — transcription disabled; students paste transcript manually
    # openai        — OpenAI Whisper API (requires OPENAI_API_KEY)
    # local_whisper — faster-whisper running locally (requires pip install faster-whisper)
    transcription_provider: str = Field(
        default="none",
        alias="TRANSCRIPTION_PROVIDER",
    )

    # ── Visual Frame Analysis ─────────────────────────────────────
    # Provider-agnostic visual analysis of captured workflow frames.
    # VISUAL_ANALYSIS_PROVIDER:
    #   none                 — disabled; returns visual_frame_analysis_status="not_configured"
    #   local_ocr            — lightweight OCR (PaddleOCR, EasyOCR, or Tesseract)
    #   local_vision         — local/open-source vision model (LLaVA, Qwen2.5-VL, etc.)
    #   openai               — OpenAI Vision API (requires OPENAI_API_KEY)
    #   veribridge_future    — reserved for future VeriBridge fine-tuned model
    # Default: none (safe — DOM evidence still works; no crash if not configured)
    visual_analysis_provider: str = Field(
        default="none",
        alias="VISUAL_ANALYSIS_PROVIDER",
    )

    # Whether the extension should capture visual frames during recording.
    # Defaults to True — the table (workflow_visual_frame_evidence) is always
    # available.  Set ENABLE_WORKFLOW_FRAME_CAPTURE=false to disable capture
    # entirely (frames will not be stored and visual_frame_analysis_status will
    # remain "not_configured").
    enable_workflow_frame_capture: bool = Field(
        default=True,
        alias="ENABLE_WORKFLOW_FRAME_CAPTURE",
    )

    # Maximum number of frames to accept per proof session.
    max_workflow_frames: int = Field(
        default=15,
        alias="MAX_WORKFLOW_FRAMES",
    )

    # LOCAL_OCR_PROVIDER: paddleocr | easyocr | tesseract
    # Only used when VISUAL_ANALYSIS_PROVIDER=local_ocr.
    # If the selected package is not installed, the service returns not_configured
    # gracefully without crashing.
    # Install: pip install paddleocr   OR   pip install easyocr   OR   pip install pytesseract
    local_ocr_provider: str = Field(
        default="paddleocr",
        alias="LOCAL_OCR_PROVIDER",
    )

    # LOCAL_VISION_PROVIDER: qwen_vl | qwen3_vl | llava | minicpm_v | blip
    # Only used when VISUAL_ANALYSIS_PROVIDER=local_vision.
    # Primary targets (open-source, recommended):
    #   qwen_vl   — Qwen2.5-VL-7B-Instruct  (requires transformers>=4.45)
    #   qwen3_vl  — Qwen3-VL-7B-Instruct    (requires transformers>=4.45)
    # Additional: llava | minicpm_v | blip
    # Install: pip install "transformers>=4.45" torch torchvision pillow accelerate qwen-vl-utils
    local_vision_provider: str = Field(
        default="qwen_vl",
        alias="LOCAL_VISION_PROVIDER",
    )

    # LOCAL_VISION_MODEL: optional override for the HuggingFace model ID.
    # When set, overrides the default model for the selected LOCAL_VISION_PROVIDER.
    # Useful for switching between 7B and 3B variants without changing provider names:
    #   Qwen/Qwen2.5-VL-7B-Instruct   (default for qwen_vl — ~14 GB, best quality)
    #   Qwen/Qwen2.5-VL-3B-Instruct   (lighter — ~6 GB, recommended for Mac CPU)
    # Example: LOCAL_VISION_MODEL=Qwen/Qwen2.5-VL-3B-Instruct
    local_vision_model: str = Field(
        default="",
        alias="LOCAL_VISION_MODEL",
    )

    # ── Advanced Visual Reasoning (Level 3) ──────────────────────────────────
    # Structured skill-evidence reasoning using Qwen2.5-VL / Qwen3-VL.
    # Runs ON TOP of existing OCR (Level 1) for richer frame analysis.
    #
    # VISUAL_REASONING_ENABLED=true enables the reasoning service.
    # Default: false (safe — OCR evidence still works; no model loaded).
    #
    # Backend selection: reuses LOCAL_VISION_PROVIDER (qwen_vl recommended).
    # Install: pip install "transformers>=4.45" torch pillow accelerate
    #
    # VISUAL_REASONING_MAX_FRAMES: number of representative frames to analyze.
    # Keep low (3-5) to control memory / latency on first run.
    #
    # Memory guidance:
    #   Qwen2.5-VL-7B: ~14 GB CPU / ~7 GB GPU (float16)
    #   Mac M-series:  supported via CPU/MPS
    #   NVIDIA GPU:    recommended for interactive speed
    visual_reasoning_enabled: bool = Field(
        default=False,
        alias="VISUAL_REASONING_ENABLED",
    )
    visual_reasoning_max_frames: int = Field(
        default=3,
        alias="VISUAL_REASONING_MAX_FRAMES",
    )

    # ── Video Keyframe Extraction ─────────────────────────────────────────────
    # Limits applied before extraction begins.  All values are configurable
    # via environment variables so they can be tightened per deployment.
    #
    # Extraction backends (no required pip install — both optional):
    #   cv2:    pip install opencv-python-headless
    #   ffmpeg: brew install ffmpeg  OR  apt install ffmpeg
    # When neither is available the endpoint returns not_available gracefully.
    max_video_size_bytes: int = Field(
        default=100 * 1024 * 1024,   # 100 MB
        alias="MAX_VIDEO_SIZE_BYTES",
    )
    max_video_duration_seconds: int = Field(
        default=300,                 # 5 minutes
        alias="MAX_VIDEO_DURATION_SECONDS",
    )
    max_video_keyframes: int = Field(
        default=10,
        alias="MAX_VIDEO_KEYFRAMES",
    )

    # OpenAI Whisper (used when transcription_provider=openai)
    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="OPENAI_API_KEY",
    )
    openai_transcription_model: str = Field(
        default="whisper-1",
        alias="OPENAI_TRANSCRIPTION_MODEL",
    )

    # local_whisper model config (used when transcription_provider=local_whisper)
    # MVP default is large-v3-turbo: on a MacBook Pro M-series it is the best
    # accuracy/speed trade-off for English project explanations and drastically
    # reduces the weak-model hallucination the `base` model produced. GPU-less
    # production (e.g. Render) can override with LOCAL_WHISPER_MODEL_SIZE=small.
    # Accepts any faster-whisper size/alias: tiny|base|small|medium|large-v3|
    # large-v3-turbo.
    local_whisper_model_size: str = Field(
        default="large-v3-turbo",
        alias="LOCAL_WHISPER_MODEL_SIZE",
    )
    # Device: cpu | cuda | auto. faster-whisper (CTranslate2) has no Metal/MPS
    # backend, so Apple Silicon must use cpu; "auto" picks cuda when available.
    local_whisper_device: str = Field(
        default="cpu",
        alias="LOCAL_WHISPER_DEVICE",
    )
    local_whisper_compute_type: str = Field(
        default="int8",
        alias="LOCAL_WHISPER_COMPUTE_TYPE",
    )
    # ── faster-whisper decoding / anti-hallucination tuning ──────────────────
    # Defaults are chosen to suppress the classic Whisper repeated-token
    # hallucination ("new new new …") seen on real screen+mic recordings:
    #   - VAD strips silence so the model is never fed dead air to hallucinate on
    #   - condition_on_previous_text=False stops a repeated token from feeding
    #     itself forward into an unbounded "new new new" loop
    #   - temperature=0 is greedy/deterministic decoding (no sampling drift)
    #   - no_speech / log_prob / compression_ratio thresholds drop low-confidence
    #     and degenerate (highly compressible ⇒ repetitive) segments
    local_whisper_beam_size: int = Field(
        default=5,
        alias="LOCAL_WHISPER_BEAM_SIZE",
    )
    local_whisper_vad: bool = Field(
        default=True,
        alias="LOCAL_WHISPER_VAD",
    )
    local_whisper_condition_on_previous_text: bool = Field(
        default=False,
        alias="LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT",
    )
    local_whisper_temperature: float = Field(
        default=0.0,
        alias="LOCAL_WHISPER_TEMPERATURE",
    )
    local_whisper_no_speech_threshold: float = Field(
        default=0.6,
        alias="LOCAL_WHISPER_NO_SPEECH_THRESHOLD",
    )
    local_whisper_compression_ratio_threshold: float = Field(
        default=2.4,
        alias="LOCAL_WHISPER_COMPRESSION_RATIO_THRESHOLD",
    )
    local_whisper_log_prob_threshold: float = Field(
        default=-1.0,
        alias="LOCAL_WHISPER_LOG_PROB_THRESHOLD",
    )
    # Language forced for local_whisper transcription.
    # For the Project Defense MVP we default to English rather than relying on
    # Whisper's auto-detection, which on short/quiet clips misfires to obscure
    # low-confidence languages (e.g. 'nn') and destabilises transcription.
    # Set LOCAL_WHISPER_LANGUAGE="" (empty) to restore Whisper auto-detection.
    local_whisper_language: str = Field(
        default="en",
        alias="LOCAL_WHISPER_LANGUAGE",
    )

    # ── Apple Wallet Passport Pass ────────────────────────────────────────────
    # "Add to Apple Wallet" for the Work Passport (Beam handoff surface).
    #
    # APPLE_WALLET_ENABLED is the master feature flag. Default false: no wallet
    # endpoints activate, no frontend button renders, and nothing in the product
    # claims Apple Wallet support. Flip to true ONLY after the Apple Developer
    # setup in docs/apple-wallet-pass-setup.md is complete.
    #
    # The pass QR always encodes the existing revocable Beam short link
    # (/b/{code}) — the pass is a carrier for that link, never a new share URL.
    #
    # Certificate/key values are FILE PATHS (or mounted secret refs), never the
    # certificate material itself. Nothing here is ever committed:
    #   APPLE_WALLET_CERT_PATH       — Pass Type ID signing certificate (PEM)
    #   APPLE_WALLET_KEY_PATH        — Pass Type ID private key (PEM)
    #   APPLE_WALLET_WWDR_CERT_PATH  — Apple WWDR G4 intermediate cert (PEM)
    #   APPLE_WALLET_KEY_PASSWORD    — password for the private key, if encrypted
    apple_wallet_enabled: bool = Field(
        default=False,
        alias="APPLE_WALLET_ENABLED",
    )
    # Pass Type identifier registered in the Apple Developer portal,
    # e.g. "pass.com.veribridgeai.passport". Empty → not configured.
    apple_pass_type_identifier: str = Field(
        default="",
        alias="APPLE_PASS_TYPE_IDENTIFIER",
    )
    # 10-character Apple Developer Team ID (Membership page). Empty → not configured.
    apple_team_identifier: str = Field(
        default="",
        alias="APPLE_TEAM_IDENTIFIER",
    )
    apple_wallet_organization_name: str = Field(
        default="VeriBridge AI",
        alias="APPLE_WALLET_ORGANIZATION_NAME",
    )
    apple_wallet_cert_path: str = Field(
        default="",
        alias="APPLE_WALLET_CERT_PATH",
    )
    apple_wallet_key_path: str = Field(
        default="",
        alias="APPLE_WALLET_KEY_PATH",
    )
    apple_wallet_wwdr_cert_path: str = Field(
        default="",
        alias="APPLE_WALLET_WWDR_CERT_PATH",
    )
    apple_wallet_key_password: SecretStr = Field(
        default=SecretStr(""),
        alias="APPLE_WALLET_KEY_PASSWORD",
    )

    # ── LLM Proof Synthesis Layer (Step 4) ───────────────────────────────────
    # Provider-agnostic, recruiter-readable synthesis of already-linked proof
    # chains.  Anthropic is NEVER required: the default is fully disabled and the
    # service always has a deterministic, rule-based fallback.  A local
    # OpenAI-compatible endpoint (Ollama / vLLM / LM Studio serving Qwen, etc.)
    # is the recommended provider so synthesis runs at zero API cost.
    #
    # LLM_SYNTHESIS_ENABLED:  master switch.  When False, the deterministic
    #   fallback is used for every chain regardless of provider.
    # LLM_SYNTHESIS_PROVIDER:  disabled | local_openai | anthropic
    #   disabled      — deterministic fallback only (default; no network).
    #   local_openai  — POST {LOCAL_LLM_BASE_URL}/chat/completions (OpenAI shape).
    #   anthropic     — Anthropic Messages API; used ONLY when ANTHROPIC_API_KEY
    #                   and AI_REVIEWER_MODEL are also configured.
    llm_synthesis_enabled: bool = Field(
        default=False,
        alias="LLM_SYNTHESIS_ENABLED",
    )
    llm_synthesis_provider: str = Field(
        default="disabled",
        alias="LLM_SYNTHESIS_PROVIDER",
    )

    # Local OpenAI-compatible endpoint (Ollama default shown).  Works unchanged
    # with vLLM / LM Studio / any OpenAI-compatible server by pointing BASE_URL
    # and MODEL at it.  The API key is a dummy for most local servers ("ollama").
    local_llm_base_url: str = Field(
        default="http://localhost:11434/v1",
        alias="LOCAL_LLM_BASE_URL",
    )
    local_llm_model: str = Field(
        default="qwen3:14b",
        alias="LOCAL_LLM_MODEL",
    )
    local_llm_api_key: SecretStr = Field(
        default=SecretStr("ollama"),
        alias="LOCAL_LLM_API_KEY",
    )

    # Per-call timeout for a single provider request (seconds).  A slow/hung
    # provider trips this and the chain falls back deterministically.
    llm_synthesis_timeout_seconds: int = Field(
        default=30,
        alias="LLM_SYNTHESIS_TIMEOUT_SECONDS",
    )
    # Bounded parallel synthesis of independent chains.  Default 1 (conservative
    # for a single local model).  Raise to 2 locally only after testing; a
    # GPU/vLLM server can run 4, 8, or more.
    llm_synthesis_max_concurrency: int = Field(
        default=1,
        alias="LLM_SYNTHESIS_MAX_CONCURRENCY",
    )
    # Upper bound on how many chains may use the LLM in one report run (cost
    # guard).  Chains beyond this still get the deterministic synthesis.
    llm_synthesis_max_chains_per_run: int = Field(
        default=20,
        alias="LLM_SYNTHESIS_MAX_CHAINS_PER_RUN",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Validators ────────────────────────────────────────────────

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url_format(cls, v: str) -> str:
        """
        Reject obviously wrong SUPABASE_URL values at startup.

        Common mistakes caught here:
          - Using the Postgres host  (db.xxx.supabase.co)
          - Using http:// instead of https://
          - Leaving the placeholder value from .env.example
          - Trailing whitespace from copy-paste
        """
        v = v.strip()
        if not v:
            return v  # empty is OK — supabase_configured checks presence

        parsed = urlparse(v)

        if parsed.scheme != "https":
            raise ValueError(
                f"SUPABASE_URL must start with 'https://'. "
                f"Found scheme: {parsed.scheme!r}. "
                "The REST API URL looks like: https://yourref.supabase.co\n"
                "Note: DATABASE_URL (the Postgres connection string) is different — "
                "do not use it here."
            )

        host = parsed.netloc.lower()
        if not host:
            raise ValueError("SUPABASE_URL has no hostname after 'https://'.")

        if not host.endswith(".supabase.co"):
            raise ValueError(
                f"SUPABASE_URL host must end with '.supabase.co'. "
                f"Got: {host!r}. "
                "Do not use the direct Postgres host (db.xxx.supabase.co); "
                "use the project REST URL (xxx.supabase.co)."
            )

        if host.startswith("db."):
            raise ValueError(
                "SUPABASE_URL appears to be the Postgres host (starts with 'db.'). "
                "Use the project REST URL instead: "
                f"https://{host[3:]} "
                "(remove the 'db.' prefix and use https://)."
            )

        return v.rstrip("/")  # normalise: strip trailing slash

    @model_validator(mode="after")
    def _reject_wildcard_cors_in_production(self) -> "Settings":
        """Fail fast if a wildcard CORS origin is configured in production.

        Allowing '*' with allow_credentials=True is both a security hazard and
        invalid per the CORS spec.  In non-production environments the wildcard
        is left untouched so local tooling keeps working.
        """
        if self.environment.strip().lower() == "production":
            if any(origin == "*" for origin in self.cors_origins):
                raise ValueError(
                    "Wildcard CORS origin '*' is not allowed when "
                    "ENVIRONMENT=production. Set CORS_ALLOWED_ORIGINS to the "
                    "explicit production origins, e.g. "
                    "https://veribridgeai.com,https://www.veribridgeai.com"
                )
        return self

    # ── Derived properties ────────────────────────────────────────

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins_raw.split(",")
            if origin.strip()
        ]

    @property
    def supabase_configured(self) -> bool:
        """True when both URL and service-role key are present."""
        return bool(
            self.supabase_url
            and self.supabase_service_role_key.get_secret_value()
        )

    @property
    def supabase_url_host(self) -> str:
        """Return only the hostname — safe to log."""
        return urlparse(self.supabase_url).netloc if self.supabase_url else ""

    @property
    def supabase_jwks_url(self) -> str:
        """The project's public JWKS endpoint for asymmetric (ES256/RS256)
        Supabase Auth tokens. Empty when SUPABASE_URL is not configured."""
        if not self.supabase_url:
            return ""
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def auth_configured(self) -> bool:
        """True when JWT verification is possible — either the legacy HS256
        secret is present or a JWKS URL can be derived for asymmetric keys."""
        return bool(
            self.supabase_jwt_secret.get_secret_value() or self.supabase_jwks_url
        )

    @property
    def apple_wallet_identifiers_configured(self) -> bool:
        """True when both Apple identifiers needed inside pass.json are set."""
        return bool(
            self.apple_pass_type_identifier.strip()
            and self.apple_team_identifier.strip()
        )

    @property
    def apple_wallet_signing_paths_configured(self) -> bool:
        """True when all three signing-material paths are set (presence only —
        the pass generator verifies the files actually exist at signing time)."""
        return bool(
            self.apple_wallet_cert_path.strip()
            and self.apple_wallet_key_path.strip()
            and self.apple_wallet_wwdr_cert_path.strip()
        )

    @property
    def anthropic_configured(self) -> bool:
        """True only when BOTH ANTHROPIC_API_KEY and AI_REVIEWER_MODEL are set.

        When False the AI Domain Reviewer falls back to deterministic rubric-based
        scoring without making any network calls.  Local development and all tests
        work without any Anthropic configuration.
        """
        return bool(
            self.anthropic_api_key.get_secret_value()
            and self.ai_reviewer_model.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
