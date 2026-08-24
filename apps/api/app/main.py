"""FastAPI application entrypoint for the API workspace."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repository root importable regardless of the current working
# directory or which Python interpreter launches uvicorn. main.py uses
# absolute ``from src.apps.api...`` imports, so the repo root (the parent
# of src/) must be on sys.path. Without this, launching from inside
# src/apps/api via ``app.main:create_app`` raises ModuleNotFoundError: No
# module named 'src'.
_REPO_ROOT = Path(__file__).resolve().parents[4]  # app/ -> api/ -> apps/ -> src/ -> root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from src.apps.api.app.api.v1.router import api_router
from src.apps.api.app.core.config import get_settings
from src.apps.api.app.core.logging_config import configure_logging
from src.apps.api.app.repositories.store import RepositoryUnavailableError


def _resolve_static_candidate(static_root: Path, full_path: str) -> Path | None:
    normalized = full_path.strip("/")
    if not normalized:
        candidate = static_root / "index.html"
        return candidate if candidate.exists() else None

    candidates = [
        static_root / normalized,
        static_root / "{0}.html".format(normalized),
        static_root / normalized / "index.html",
    ]
    static_root_resolved = static_root.resolve()
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            candidate.resolve().relative_to(static_root_resolved)
        except ValueError:
            continue
        return candidate
    fallback = static_root / "index.html"
    return fallback if fallback.exists() else None


def create_app() -> FastAPI:
    # Configure console logging once, before anything else starts emitting.
    # FORMAT: 2026-08-14 21:03:12  INFO  src.apps.api...  func:line  message
    # Level via LOG_LEVEL (default INFO; DEBUG for app loggers).
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="AI ReqEval API",
        version="0.1.0",
        description="Backend API for the AI requirement evaluation platform.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RepositoryUnavailableError)
    async def repository_unavailable_handler(
        _request: Request,
        exc: RepositoryUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "存储服务暂不可用，请确认 MongoDB 可连接后重试。",
                "collection": exc.collection_name,
                "operation": exc.operation,
            },
        )

    app.include_router(api_router, prefix="/api/v1")

    static_root = settings.static_root
    if static_root.exists():
        @app.get("/", include_in_schema=False)
        async def serve_root() -> FileResponse:
            candidate = _resolve_static_candidate(static_root, "")
            if candidate is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Static index.html not found")
            return FileResponse(candidate)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_frontend(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API route not found")
            candidate = _resolve_static_candidate(static_root, full_path)
            if candidate is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Static asset not found")
            return FileResponse(candidate)
    return app


def main() -> int:
    _ = create_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
