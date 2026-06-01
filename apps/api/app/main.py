import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


def _log_visual_reasoning_config() -> None:
    """Log Qwen / visual reasoning configuration at startup."""
    enabled = settings.visual_reasoning_enabled
    provider = settings.local_vision_provider
    model = settings.local_vision_model or "(default for provider)"
    max_frames = settings.visual_reasoning_max_frames
    logger.info("Visual reasoning enabled: %s", enabled)
    logger.info("Local vision provider: %s", provider if enabled else "none")
    logger.info("Local vision model: %s", model if enabled else "—")
    logger.info("Visual reasoning max frames: %d", max_frames)
    if not enabled:
        logger.info(
            "To enable Qwen visual reasoning, start with: "
            "VISUAL_REASONING_ENABLED=true LOCAL_VISION_PROVIDER=qwen_vl "
            "LOCAL_VISION_MODEL=Qwen/Qwen2.5-VL-3B-Instruct VISUAL_REASONING_MAX_FRAMES=2 "
            "uvicorn app.main:app --reload --port 8000"
        )


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.on_event("startup")
    async def on_startup() -> None:
        logging.basicConfig(level=logging.INFO)
        _log_visual_reasoning_config()

    return app


app = create_app()
