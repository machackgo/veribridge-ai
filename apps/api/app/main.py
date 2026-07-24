import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.v1.router import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


class SafeInternalErrorMiddleware:
    """Convert unhandled exceptions into a safe JSON 500 *inside* CORS.

    Starlette's default ServerErrorMiddleware sits OUTSIDE CORSMiddleware, so an
    unhandled exception produces a plain-text 500 with no CORS headers — the
    browser then blocks the response and every caller sees a bare
    ``TypeError: Failed to fetch`` instead of a real error (production incident:
    passport publish FK 23503 surfacing as "Failed to fetch"). Because this
    middleware is added BEFORE CORSMiddleware it runs inside it, so its response
    passes back through CORS and gets the Access-Control-Allow-Origin header.

    The body never leaks the exception — same shape as HTTPException details.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def sentinel_send(message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, sentinel_send)
        except Exception:
            logger.exception(
                "Unhandled error on %s %s", scope.get("method"), scope.get("path")
            )
            if response_started:
                # Headers already sent — nothing safe left to write.
                raise
            response = JSONResponse(
                {
                    "detail": {
                        "code": "internal_error",
                        "message": "Something went wrong on our side. Please try again.",
                    }
                },
                status_code=500,
            )
            await response(scope, receive, send)


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

    # Added BEFORE CORSMiddleware so CORS wraps it (last-added is outermost):
    # its safe JSON 500 flows back through CORS and keeps the ACAO header.
    app.add_middleware(SafeInternalErrorMiddleware)

    @app.middleware("http")
    async def no_store_public_responses(request, call_next):
        # Public surfaces honor the Passport visibility switch; forbidding
        # browser/CDN caching keeps Public → Private revocation immediate.
        response = await call_next(request)
        if request.url.path.startswith(f"{settings.api_v1_prefix}/public/"):
            response.headers["Cache-Control"] = "no-store"
        return response

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
