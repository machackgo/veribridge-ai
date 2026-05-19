from fastapi import APIRouter

from app.api.v1.endpoints import (
    debug,
    github_semantic_verification_results,
    health,
    skill_evidence,
    student,
    website_browser_verification_runs,
    website_semantic_verification_results,
    website_verification_runs,
)

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
    website_verification_runs.router,
    prefix="/student/skill-evidence",
    tags=["website-verification-runs"],
)
api_router.include_router(
    website_browser_verification_runs.router,
    prefix="/student/skill-evidence",
    tags=["website-browser-verification-runs"],
)
api_router.include_router(
    github_semantic_verification_results.router,
    prefix="/student/skill-evidence",
    tags=["github-semantic-verification-results"],
)
api_router.include_router(
    website_semantic_verification_results.router,
    prefix="/student/skill-evidence",
    tags=["website-semantic-verification-results"],
)
api_router.include_router(
    debug.router,
    prefix="/debug",
    tags=["debug"],
)
