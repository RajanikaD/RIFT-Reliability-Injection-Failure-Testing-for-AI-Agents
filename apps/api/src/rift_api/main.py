"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from rift_api.config import Settings, get_settings


class HealthResponse(BaseModel):
    """Response returned by the API health check."""

    status: Literal["ok"]
    service: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API application with validated runtime settings."""

    runtime_settings = settings or get_settings()
    application = FastAPI(
        title="RIFT API",
        debug=runtime_settings.debug,
    )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service=runtime_settings.service_name)

    return application


app = create_app()
