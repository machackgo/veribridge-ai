from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.health import DependencyHealthResponse, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Cheap liveness probe (used by the platform health check).

    Deliberately touches nothing external so a transient dependency blip can
    never restart-loop the service.
    """
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/health/dependencies", response_model=DependencyHealthResponse)
def dependency_health_check(db: Any = Depends(get_db)) -> DependencyHealthResponse:
    """Deep readiness probe: verifies the database is actually reachable.

    /health alone reads "ok" through a full Supabase outage, which made real
    outages invisible until a student reported one. This endpoint is for
    operators/monitors — it is NOT wired to the platform health check.
    """
    database = "ok"
    try:
        db.table("users").select("id").limit(1).execute()
    except Exception:  # noqa: BLE001 — any failure means "not reachable"
        database = "unreachable"
    return DependencyHealthResponse(
        status="ok" if database == "ok" else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        database=database,
    )
