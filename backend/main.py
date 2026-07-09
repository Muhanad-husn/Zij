"""FastAPI application factory (contract: design/contracts/api.md).

Exposes `GET /api/health`, `GET /api/config`, the per-layer snapshot/refresh
endpoints (issue #18), and mounts the built frontend as static files at `/`
(`/api/*` takes precedence over the static fallback).

`create_app` is an explicit factory so tests can inject a hermetic
`static_dir` plus a controlled `config`/`secrets` pair rather than depending
on `load_config()` and a real frontend build (backend/tests/test_api.py). It
also accepts optional `air_adapter`/`land_adapter`/`store` collaborators
(each defaulted from `config`/`secrets` when omitted) so tests can inject
respx-mockable adapters and a hermetic `Store`. The module-level `app` below
is the real uvicorn entrypoint, built lazily from `load_config()` and the
real frontend build directory so importing this module never fails even
before the frontend is built.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.config import AppConfig, Secrets, load_config
from backend.events import EventBus
from backend.integrity import CAVEATS, active_flag_counts
from backend.models import (
    Domain,
    Feature,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.registry import Registry
from backend.sources.base import (
    AdapterError,
    AuthError,
    ParseError,
    RateLimitedError,
    Region,
    UpstreamError,
)
from backend.sources.opensky import CreditLedger, OpenSkyAdapter, OpenSkyCfg
from backend.sources.overpass import OverpassAdapter, OverpassCfg
from backend.store import ConflictError, LandCacheRow, Store

_LOG = logging.getLogger(__name__)

# storage.md: "serve from cache if now - fetched_at < 24h".
_LAND_CACHE_FRESH_S = 86400

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


def _coerce_domain(domain: str) -> Domain:
    """`str` path param -> `Domain`, raising the api.md `bad_request` envelope
    for anything outside `{air, marine, land}`."""
    try:
        return Domain(domain)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error_envelope("bad_request", f"unknown domain {domain!r}"),
        ) from exc


class _PresetCreateRequest(BaseModel):
    name: str
    bbox: tuple[float, float, float, float]


def _adapter_error_to_http(exc: AdapterError) -> HTTPException:
    """Map a raised `AdapterError` (adapter-interface.md) to the api.md error
    envelope + matching HTTP status."""
    if isinstance(exc, RateLimitedError):
        message = str(exc) or "upstream rate limit exceeded"
        body = _error_envelope("rate_limited", message, retry_after_s=exc.retry_after)
        headers = (
            {"Retry-After": str(round(exc.retry_after))}
            if exc.retry_after is not None
            else None
        )
        return HTTPException(status_code=429, detail=body, headers=headers)
    if isinstance(exc, AuthError):
        body = _error_envelope(
            "auth_error", str(exc) or "upstream authentication error"
        )
        return HTTPException(status_code=401, detail=body)
    if isinstance(exc, (UpstreamError, ParseError)):
        body = _error_envelope("upstream_error", str(exc) or "upstream error")
        return HTTPException(status_code=502, detail=body)
    body = _error_envelope("internal", str(exc) or "internal error")
    return HTTPException(status_code=500, detail=body)


def _feature_to_geojson(feature: Feature) -> dict[str, Any]:
    """Convert a Zij `Feature` to a GeoJSON `Feature` for `land_cache.geojson`
    (storage.md: "simplified FeatureCollection"). `geometry` carries the
    line/polygon geometry when present, else a synthesized `Point` from
    `lat`/`lon`; every other `Feature` field (including `lat`/`lon`
    themselves, so the round-trip is lossless) rides in `properties`."""
    properties = feature.model_dump(mode="json")
    geometry = properties.pop("geometry")
    if geometry is None:
        geometry = {"type": "Point", "coordinates": [feature.lon, feature.lat]}
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _geojson_to_feature(gj_feature: dict[str, Any]) -> Feature:
    """Inverse of `_feature_to_geojson`: reconstruct a `Feature` from a
    GeoJSON `Feature` produced by it. Point features carry `geometry=None` on
    the Zij `Feature` (feature-schema.md), so the synthesized `Point`
    geometry is dropped rather than round-tripped back into the field."""
    properties = dict(gj_feature["properties"])
    if properties.get("geometry_type") == GeometryType.POINT.value:
        properties["geometry"] = None
    else:
        properties["geometry"] = gj_feature.get("geometry")
    return Feature.model_validate(properties)


def _land_snapshot_to_feature_collection(snapshot: LayerSnapshot) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [_feature_to_geojson(feature) for feature in snapshot.features],
    }


def _land_snapshot_from_cache_row(
    row: LandCacheRow, *, cadence_s: int, stale_after_s: int
) -> LayerSnapshot:
    features = [_geojson_to_feature(gj) for gj in row.geojson.get("features", [])]
    meta = LayerSnapshotMeta(
        layer=Domain.LAND,
        region_id=row.region_id,
        status=LayerStatus.LIVE,
        timestamp_fetched=row.fetched_at,
        timestamp_source=row.osm_base,
        cadence_s=cadence_s,
        stale_after_s=stale_after_s,
        feature_count=row.feature_count,
    )
    return LayerSnapshot(meta=meta, features=features)


def create_app(
    *,
    static_dir: Path | str,
    config: AppConfig,
    secrets: Secrets,
    air_adapter: OpenSkyAdapter | None = None,
    land_adapter: OverpassAdapter | None = None,
    store: Store | None = None,
    registry: Registry | None = None,
    events: EventBus | None = None,
) -> FastAPI:
    """Build the Zij FastAPI app.

    `secrets` is never referenced in any response body -- only `config` is
    ever serialized (NFR5) -- but is used to build the default `air_adapter`
    when one isn't injected. `air_adapter`/`land_adapter`/`store`/`registry`/
    `events` are each optional and default to a fresh/real collaborator built
    from `config`/`secrets` when omitted, so the real uvicorn entrypoint
    (`_build_default_app`) keeps working unchanged.
    """
    if air_adapter is None:
        opensky_cfg = OpenSkyCfg(**config.opensky, **config.layers["air"].model_dump())
        credits = CreditLedger(
            budget=opensky_cfg.daily_credit_budget,
            warn_ratio=opensky_cfg.credit_warn_ratio,
        )
        air_adapter = OpenSkyAdapter(opensky_cfg, secrets, credits)
    if land_adapter is None:
        overpass_cfg = OverpassCfg(
            **config.overpass, **config.layers["land"].model_dump()
        )
        land_adapter = OverpassAdapter(overpass_cfg)
    if store is None:
        store = Store()
    if registry is None:
        registry = Registry()
    if events is None:
        events = EventBus()

    land_cfg = config.layers["land"]
    land_cadence_s = land_cfg.cadence_s
    land_stale_after_s = land_cfg.cadence_s * land_cfg.stale_multiplier

    hormuz_cfg = next(region for region in config.regions if region.id == "hormuz")
    hormuz_region = Region(
        id=hormuz_cfg.id, label=hormuz_cfg.label, bbox=hormuz_cfg.bbox
    )

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # `Store` uses an `asyncio.Lock`; it must be initialized on the same
        # event loop the async handlers run on, hence startup-time (not
        # construction-time) init.
        await store.init()
        try:
            yield
        finally:
            await air_adapter.stop()
            await land_adapter.stop()
            await store.close()

    app = FastAPI(lifespan=_lifespan)
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

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Catch-all so every non-2xx response uses the api.md envelope (api.md
        # "Error envelope"), even for faults the handlers don't explicitly
        # catch (e.g. a non-`AdapterError` from a collaborator). The message
        # is a fixed generic string -- the exception text is never
        # interpolated into the response body -- so internals/secrets never
        # leak into a client-visible error (NFR5 spirit).
        del request
        _LOG.exception("unhandled exception in request handler", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_envelope("internal", "internal server error"),
        )

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

    async def _fetch_and_cache_land() -> LayerSnapshot:
        """Force a fresh Overpass fetch and write it through to
        `land_cache`, bypassing the freshness check (used by both the cold
        cache path and `POST /api/refresh`)."""
        snapshot = await land_adapter.fetch(hormuz_region)
        row = LandCacheRow(
            region_id=hormuz_region.id,
            bbox=hormuz_region.bbox,
            geojson=_land_snapshot_to_feature_collection(snapshot),
            feature_count=snapshot.meta.feature_count,
            osm_base=snapshot.meta.timestamp_source,
            fetched_at=snapshot.meta.timestamp_fetched,
        )
        await store.put_land_cache(row)
        return snapshot

    @app.get("/api/layers/air/snapshot")
    async def get_air_snapshot() -> dict:
        try:
            snapshot = await air_adapter.fetch(hormuz_region)
        except AdapterError as exc:
            raise _adapter_error_to_http(exc) from exc
        return snapshot.model_dump(mode="json")

    @app.get("/api/layers/land/snapshot")
    async def get_land_snapshot() -> dict:
        try:
            cached = await store.get_land_cache(hormuz_region.id)
            if cached is not None:
                age_s = (datetime.now(timezone.utc) - cached.fetched_at).total_seconds()
                if age_s < _LAND_CACHE_FRESH_S:
                    snapshot = _land_snapshot_from_cache_row(
                        cached,
                        cadence_s=land_cadence_s,
                        stale_after_s=land_stale_after_s,
                    )
                    return snapshot.model_dump(mode="json")
            snapshot = await _fetch_and_cache_land()
        except AdapterError as exc:
            raise _adapter_error_to_http(exc) from exc
        return snapshot.model_dump(mode="json")

    @app.post("/api/refresh", status_code=202)
    async def refresh() -> dict:
        # v0 is manual-refresh-only (no scheduler): force both layers to
        # refetch inline. FR10 isolation -- one layer's failure never aborts
        # the other's refresh.
        try:
            await air_adapter.fetch(hormuz_region)
        except AdapterError:
            _LOG.warning("POST /api/refresh: air layer refetch failed", exc_info=True)
        try:
            await _fetch_and_cache_land()
        except AdapterError:
            _LOG.warning("POST /api/refresh: land layer refetch failed", exc_info=True)
        return {"queued": ["air", "land"]}

    @app.get("/api/layers/{domain}/caveats")
    async def get_layer_caveats(domain: str) -> dict:
        domain_enum = _coerce_domain(domain)
        snapshot = registry.get(domain_enum)
        if snapshot is None:
            # api.md: static caveats + "any active integrity-flag counts from
            # the current snapshot" -- with no snapshot yet, that's every
            # flag at 0. Reuse `active_flag_counts` (rather than hand-roll
            # the zero dict) via a minimal `.features`-bearing stand-in.
            active_flags = active_flag_counts(SimpleNamespace(features=[]))
        else:
            active_flags = active_flag_counts(snapshot)
        return {
            "domain": domain_enum.value,
            "caveats": CAVEATS[domain_enum],
            "active_flags": active_flags,
        }

    @app.get("/api/features/{domain}/{source_id}/raw")
    async def get_feature_raw(domain: str, source_id: str) -> dict:
        domain_enum = _coerce_domain(domain)
        snapshot = registry.get(domain_enum)
        feature = None
        if snapshot is not None:
            feature = next(
                (f for f in snapshot.features if f.source_id == source_id), None
            )
        if feature is None:
            raise HTTPException(
                status_code=404,
                detail=_error_envelope(
                    "not_found",
                    f"no live {domain_enum.value} feature with source_id {source_id!r}",
                ),
            )
        return {
            "domain": domain_enum.value,
            "source_id": feature.source_id,
            "source": feature.source,
            "raw_payload": feature.raw_payload,
        }

    @app.get("/api/presets")
    async def list_presets() -> dict:
        rows = await store.list_presets()
        return {
            "presets": [
                {
                    "id": row.id,
                    "name": row.name,
                    "bbox": list(row.bbox),
                    "created_at": row.created_at.isoformat().replace("+00:00", "Z"),
                }
                for row in rows
            ]
        }

    @app.post("/api/presets", status_code=201)
    async def create_preset(payload: _PresetCreateRequest) -> dict:
        try:
            preset_id = await store.add_preset(
                payload.name, payload.bbox, label=payload.name
            )
        except ConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_envelope("conflict", str(exc)),
            ) from exc
        rows = await store.list_presets()
        created = next(row for row in rows if row.id == preset_id)
        return {
            "id": created.id,
            "name": created.name,
            "bbox": list(created.bbox),
            "created_at": created.created_at.isoformat().replace("+00:00", "Z"),
        }

    @app.delete("/api/presets/{preset_id}", status_code=204)
    async def delete_preset(preset_id: int) -> None:
        await store.delete_preset(preset_id)
        return None

    # Monotonic per-connection-independent counter for the SSE `id:` field
    # (api.md "## SSE": "Each event has ... a monotonic id:") -- shared
    # across the app so ids only ever increase, which is what makes
    # `Last-Event-ID` a meaningful (if advisory) cursor.
    _sse_event_id = itertools.count(1)

    async def _sse_stream(request: Request):
        """Full-state-on-connect (ADR-12): replay one `snapshot` per
        **enabled** layer present in `registry` (raw_payload already
        excluded via `Feature.raw_payload`'s `exclude=True`), then stream
        incrementals from this connection's subscriber queue until the
        client disconnects."""
        queue = events.subscribe()
        try:
            for domain, snapshot in list(registry.items()):
                layer_cfg = config.layers.get(domain.value)
                if layer_cfg is None or not layer_cfg.enabled:
                    continue
                yield {
                    "event": "snapshot",
                    "id": str(next(_sse_event_id)),
                    "data": json.dumps(snapshot.model_dump(mode="json")),
                }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield {
                    "event": item["event"],
                    "id": str(next(_sse_event_id)),
                    "data": json.dumps(item["data"]),
                }
        finally:
            events.unsubscribe(queue)

    @app.get("/api/events")
    async def sse_events(request: Request) -> EventSourceResponse:
        ping_s = config.server.get("sse_ping_s", 15)
        return EventSourceResponse(_sse_stream(request), ping=ping_s)

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
    static_dir = (
        _FRONTEND_DIST if _FRONTEND_DIST.is_dir() else Path(__file__).resolve().parent
    )
    return create_app(static_dir=static_dir, config=config, secrets=secrets)


app = _build_default_app()
