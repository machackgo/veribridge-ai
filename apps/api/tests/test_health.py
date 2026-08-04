from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app


def test_health_check() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "careerproof-api",
        "version": "0.1.0",
    }


class _OkDb:
    def table(self, _name: str) -> "_OkDb":
        return self

    def select(self, _cols: str) -> "_OkDb":
        return self

    def limit(self, _n: int) -> "_OkDb":
        return self

    def execute(self) -> dict:
        return {"data": []}


class _DownDb(_OkDb):
    def execute(self) -> dict:
        raise ConnectionError("db unreachable")


def test_dependency_health_ok() -> None:
    app.dependency_overrides[get_db] = lambda: _OkDb()
    try:
        response = TestClient(app).get("/api/v1/health/dependencies")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_dependency_health_degraded_when_db_unreachable() -> None:
    app.dependency_overrides[get_db] = lambda: _DownDb()
    try:
        response = TestClient(app).get("/api/v1/health/dependencies")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
