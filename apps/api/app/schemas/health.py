from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class DependencyHealthResponse(HealthResponse):
    database: str
