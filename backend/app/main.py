import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api import health, sessions
from app.config import get_settings
from app.db import run_migrations
from app.llm import LLMError
from app.orchestrator import SessionStateError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    run_migrations()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # SRS 5.2: errors use standard HTTP codes with a JSON body {"error": "..."}
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"{loc}: {first.get('msg', 'invalid input')}" if loc else first.get("msg", "invalid input")
        return JSONResponse(status_code=422, content={"error": msg})

    # NFR-11: after retries, show a friendly error and keep the session
    @app.exception_handler(LLMError)
    async def llm_error(_: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": exc.user_message})

    @app.exception_handler(SessionStateError)
    async def state_error(_: Request, exc: SessionStateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    app.include_router(health.router)
    app.include_router(sessions.router)
    return app


app = create_app()
