"""FastAPI entry point for the initial FloodOps backend foundation."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import drainage, flood, integration, route, storms
from app.config import get_settings
from app.schemas import HealthResponse

logger = logging.getLogger("floodops")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting %s", get_settings().app_name)
    yield
    logger.info("Stopping %s", get_settings().app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="FloodOps integration API. P9 endpoints serve only existing validated outputs.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "details": exc.errors()},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception):
        logger.exception("Unhandled application error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_server_error", "message": "An unexpected error occurred."},
        )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            service=settings.app_name,
            environment=settings.app_env,
            message="FloodOps backend is running.",
        )

    application.include_router(flood.router)
    application.include_router(route.router)
    application.include_router(drainage.router)
    application.include_router(storms.router)
    application.include_router(integration.router)
    return application


app = create_app()


def run() -> None:
    """Run the API with the configured host and port when invoked as a module."""

    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":
    run()
