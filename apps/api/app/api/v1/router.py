from fastapi import APIRouter

from app.api.v1.endpoints import debug, health, skill_evidence, student

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(
    student.router,
    prefix="/student",
    tags=["student"],
)
api_router.include_router(
    skill_evidence.router,
    prefix="/student/skill-evidence",
    tags=["skill-evidence"],
)
api_router.include_router(
    debug.router,
    prefix="/debug",
    tags=["debug"],
)
