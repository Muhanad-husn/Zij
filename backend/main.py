"""FastAPI application factory (contract: design/contracts/api.md).

Exposes `GET /api/health`, `GET /api/config`, and mounts the built frontend
as static files at `/` (`/api/*` takes precedence over the static fallback).

`create_app` is an explicit factory so tests can inject a hermetic
`static_dir` plus a controlled `config`/`secrets` pair rather than depending
on `load_config()` and a real frontend build (backend/tests/test_api.py).
The module-level `app` below is the real uvicorn entrypoint, built lazily
from `load_config()` and the real frontend build directory so importing
this module never fails even before the frontend is built.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import AppConfig, Secrets, load_config

__version__ = "0.1.0"

# Status codes matching each api.md error envelope `code` (api.md "Error
# envelope").
_ERROR_STATUS: dict[str, int] = {
    "bad_request": 400,
    "auth_error": 401,
    "not_found": 404,
    "conflict": 409,
    "validation_error": 422,
    "rate_limited": 429,
    "internal": 500,
    "upstream_error": 502,
}

# Reverse lookup: HTTP status -> envelope `code`, for exceptions raised
# without an explicit code (e.g. Starlette's own 404 on an unmatched route).
_STATUS_TO_CODE: dict[int, str] = {
    status: code for code, status in _ERROR_STATUS.items()
}


def _error_envelope(code: str, message: str, **extra: object) -> dict:
    """Build the api.md error envelope body for a given `code`."""
    body: dict[str, object] = {"code": code, "message": message}
    body.update(extra)
    return {"error": body}


def create_app(*, static_dir: Path | str, config: AppConfig, secrets: Secrets) -> FastAPI:
    """Build the Zij FastAPI app.

    `secrets` is accepted (per api.md's implied startup shape and NFR5) but
    deliberately never referenced in any response -- only `config` is ever
    serialized.
    """
    del secrets  # never serialized (NFR5); accepted for signature/startup parity

    app = FastAPI()
    start_monotonic = time.monotonic()

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        del request
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            body = detail
        else:
            code = _STATUS_TO_CODE.get(exc.status_code, "internal")
            message = detail if isinstance(detail, str) else code
            body = _error_envelope(code, message)
        headers = dict(exc.headers) if exc.headers else None
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "uptime_s": time.monotonic() - start_monotonic,
        }

    @app.get("/api/config")
    async def get_config() -> dict:
        return config.model_dump(mode="json")

    @app.get("/api/{rest:path}")
    async def api_catch_all(rest: str) -> None:
        del rest
        raise HTTPException(status_code=404, detail="not found")

    # Mounted last so the explicit /api/* routes above are matched first.
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _build_default_app() -> FastAPI:
    """Build the real uvicorn-entrypoint app.

    `load_config()` errors (e.g. `MissingSecretError`) are allowed to
    propagate: an enabled layer's missing required secret must fail startup
    fast per design/contracts/config.md, not be silently swallowed. The
    frontend build directory, however, is genuinely optional at import time
    (e.g. before `frontend/dist` exists), so that fallback stays defensive.
    """
    config, secrets = load_config()
    static_dir = _FRONTEND_DIST if _FRONTEND_DIST.is_dir() else Path(__file__).resolve().parent
    return create_app(static_dir=static_dir, config=config, secrets=secrets)


app = _build_default_app()
