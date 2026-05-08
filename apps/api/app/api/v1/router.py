from fastapi import APIRouter

from app.api.v1.endpoints import debug, health, student

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(
    student.router,
    prefix="/student",
    tags=["student"],
)
api_router.include_router(
    debug.router,
    prefix="/debug",
    tags=["debug"],
)
