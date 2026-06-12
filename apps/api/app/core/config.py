from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App identity ──────────────────────────────────────────────
    app_name: str = Field(default="careerproof-api", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    # ── CORS ─────────────────────────────────────────────────────
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        alias="CORS_ORIGINS",
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
    # SUPABASE_JWT_SECRET signs all Supabase Auth JWTs with HS256.
    # Find it at: Supabase dashboard → Settings → API → JWT Settings → JWT Secret.
    # Required for token verification in production.
    # When absent (dev only), falls back to DEMO_USER_ID.
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
    local_whisper_model_size: str = Field(
        default="base",
        alias="LOCAL_WHISPER_MODEL_SIZE",
    )
    local_whisper_device: str = Field(
        default="cpu",
        alias="LOCAL_WHISPER_DEVICE",
    )
    local_whisper_compute_type: str = Field(
        default="int8",
        alias="LOCAL_WHISPER_COMPUTE_TYPE",
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
    def auth_configured(self) -> bool:
        """True when JWT verification is possible (secret is present)."""
        return bool(self.supabase_jwt_secret.get_secret_value())

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
