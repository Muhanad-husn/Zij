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
import contextlib
import itertools
import json
import logging
import time
import uuid
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

from backend.config import AppConfig, Secrets, estimate_credits, load_config
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
from backend.scheduler import Scheduler
from backend.sources.aisstream import AisStreamAdapter, AisStreamCfg
from backend.sources.base import (
    AdapterError,
    AuthError,
    ParseError,
    RateLimitedError,
    Region,
    StreamAdapter,
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


class _RegionEstimateRequest(BaseModel):
    bbox: tuple[float, float, float, float]


class _RegionActivateRequest(BaseModel):
    region_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    label: str | None = None
    save_as_preset: bool = False


class _LayerToggleRequest(BaseModel):
    enabled: bool


def _region_info(
    region_id: str, label: str, bbox: tuple[float, float, float, float], kind: str
) -> dict:
    """A `RegionInfo`-shaped dict (api.md "GET /api/regions" example): no
    frozen pydantic model exists in `design/` for this shape, so a plain
    dict literal is the lighter-touch choice, consistent with every other
    ad-hoc response body already built this way in this module."""
    return {
        "id": region_id,
        "label": label,
        "bbox": list(bbox),
        "aviation_credit_cost": estimate_credits(bbox),
        "kind": kind,
    }


def _estimate_bbox(config: AppConfig, bbox: tuple[float, float, float, float]) -> dict:
    """Pure estimate math (api.md "POST /api/regions/estimate"): area, the
    aviation credit-tier cost, and a per-layer cap comparison. Reused
    verbatim by `POST /api/regions/activate`'s server-side re-validation of
    a custom bbox (api.md: "Custom bbox is re-validated server-side")."""
    west, south, east, north = bbox
    area_sq_deg = (east - west) * (north - south)
    aviation_credit_cost = estimate_credits(bbox)
    layer_caps: dict[str, dict] = {}
    valid = True
    for domain_name, layer_cfg in config.layers.items():
        cap = layer_cfg.custom_bbox_cap_sq_deg
        ok = area_sq_deg <= cap
        entry: dict[str, object] = {"ok": ok, "cap_sq_deg": cap}
        if domain_name == Domain.AIR.value:
            entry["cost_credits"] = aviation_credit_cost
        if not ok:
            entry["message"] = (
                f"{domain_name.capitalize()} bbox {area_sq_deg} sq° "
                f"exceeds the {cap} sq° cap."
            )
            valid = False
        layer_caps[domain_name] = entry
    return {
        "valid": valid,
        "bbox": list(bbox),
        "area_sq_deg": area_sq_deg,
        "aviation_credit_cost": aviation_credit_cost,
        "layer_caps": layer_caps,
    }


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
    marine_adapter: StreamAdapter | None = None,
    store: Store | None = None,
    registry: Registry | None = None,
    events: EventBus | None = None,
    scheduler: Scheduler | None = None,
) -> FastAPI:
    """Build the Zij FastAPI app.

    `secrets` is never referenced in any response body -- only `config` is
    ever serialized (NFR5) -- but is used to build the default `air_adapter`
    /`marine_adapter` when one isn't injected. `air_adapter`/`land_adapter`/
    `marine_adapter`/`store`/`registry`/`events`/`scheduler` are each
    optional and default to a fresh/real collaborator built from
    `config`/`secrets` when omitted, so the real uvicorn entrypoint
    (`_build_default_app`) keeps working unchanged.

    The default `scheduler` is wired with `marine_adapter` as its `stream`
    collaborator, and its `run()` task loop IS started as a background task
    by the lifespan below (issue #113) -- the scheduler's poll loops and the
    marine `_stream_supervisor` genuinely run for the app's lifetime.
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
    if marine_adapter is None:
        aisstream_cfg = AisStreamCfg(
            **config.aisstream, **config.layers["marine"].model_dump()
        )
        marine_adapter = AisStreamAdapter(aisstream_cfg, secrets)
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

    # The region resolved by `load_config` (config.md "Precedence" #5),
    # else the app's hardcoded pre-scheduler default -- used both as the
    # default scheduler's initial region and as `GET /api/regions/active`'s
    # initial state before any `POST /api/regions/activate` call.
    active_region_cfg = next(
        (r for r in config.regions if r.id == config.active_region_id),
        hormuz_cfg,
    )
    active_region_state: dict[str, dict | None] = {
        "info": _region_info(
            active_region_cfg.id,
            active_region_cfg.label,
            active_region_cfg.bbox,
            "predefined",
        )
    }

    if scheduler is None:
        scheduler = Scheduler(
            config,
            {Domain.AIR: air_adapter, Domain.LAND: land_adapter},
            Region(
                id=active_region_cfg.id,
                label=active_region_cfg.label,
                bbox=active_region_cfg.bbox,
            ),
            registry=registry,
            store=store,
            events=events,
            stream=marine_adapter,
        )

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # `Store` uses an `asyncio.Lock`; it must be initialized on the same
        # event loop the async handlers run on, hence startup-time (not
        # construction-time) init.
        await store.init()
        # The scheduler owns the app's background loops (poll tasks + the
        # marine `_stream_supervisor`) for the app's lifetime (issue #113,
        # scheduler.md "Task model": "lifetime = app lifetime").
        scheduler_task = asyncio.create_task(scheduler.run())
        try:
            yield
        finally:
            scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, BaseExceptionGroup):
                await scheduler_task
            await air_adapter.stop()
            await land_adapter.stop()
            await marine_adapter.stop()
            await store.close()

    app = FastAPI(lifespan=_lifespan)
    app.state.scheduler = scheduler
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

    @app.get("/api/regions")
    async def list_regions() -> dict:
        regions = [
            _region_info(region_cfg.id, region_cfg.label, region_cfg.bbox, "predefined")
            for region_cfg in config.regions
        ]
        preset_rows = await store.list_presets()
        regions.extend(
            _region_info(f"custom:{row.id}", row.label, row.bbox, "preset")
            for row in preset_rows
        )
        return {"regions": regions}

    @app.post("/api/regions/estimate")
    async def estimate_region(payload: _RegionEstimateRequest) -> dict:
        result = _estimate_bbox(config, payload.bbox)
        if not result["valid"]:
            raise HTTPException(
                status_code=422,
                detail=_error_envelope(
                    "validation_error",
                    "custom bbox exceeds a layer cap",
                    details=result,
                ),
            )
        return result

    @app.post("/api/regions/activate")
    async def activate_region_route(payload: _RegionActivateRequest) -> dict:
        if payload.region_id is not None:
            region_cfg = next(
                (r for r in config.regions if r.id == payload.region_id), None
            )
            if region_cfg is None:
                raise HTTPException(
                    status_code=404,
                    detail=_error_envelope(
                        "not_found", f"unknown region_id {payload.region_id!r}"
                    ),
                )
            region = Region(
                id=region_cfg.id, label=region_cfg.label, bbox=region_cfg.bbox
            )
            kind = "predefined"
        else:
            if payload.bbox is None:
                raise HTTPException(
                    status_code=400,
                    detail=_error_envelope(
                        "bad_request",
                        "activate requires either region_id or bbox",
                    ),
                )
            estimate = _estimate_bbox(config, payload.bbox)
            if not estimate["valid"]:
                raise HTTPException(
                    status_code=422,
                    detail=_error_envelope(
                        "validation_error",
                        "custom bbox exceeds a layer cap",
                        details=estimate,
                    ),
                )
            label = payload.label or "Custom region"
            region_id = f"custom:{uuid.uuid4().hex[:8]}"
            kind = "custom"
            if payload.save_as_preset:
                try:
                    preset_id = await store.add_preset(label, payload.bbox, label=label)
                except ConflictError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=_error_envelope("conflict", str(exc)),
                    ) from exc
                region_id = f"custom:{preset_id}"
                kind = "preset"
            region = Region(id=region_id, label=label, bbox=payload.bbox)

        await scheduler.activate_region(region)
        info = _region_info(region.id, region.label, region.bbox, kind)
        active_region_state["info"] = info
        return {"active_region": info}

    @app.get("/api/regions/active")
    async def get_active_region() -> dict:
        return {"active_region": active_region_state["info"]}

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

    @app.get("/api/layers/{domain}/snapshot")
    async def get_layer_snapshot(domain: str) -> dict:
        """Consolidated air/land/marine snapshot route (#37) -- one route
        for all three domains now that marine is a third live domain. Air
        and land keep their pre-scheduler direct-fetch behavior exactly
        (backend/tests/test_api.py::test_snapshots_and_refresh locks this
        in); marine (and any future registry-only domain) pulls the current
        `LayerSnapshot` from the registry -- the scheduler is its sole
        writer -- 404 `not_found` when nothing has been fetched yet for it
        (api.md: "404 not_found if no active region")."""
        domain_enum = _coerce_domain(domain)
        if domain_enum is Domain.AIR:
            try:
                snapshot = await air_adapter.fetch(hormuz_region)
            except AdapterError as exc:
                raise _adapter_error_to_http(exc) from exc
            return snapshot.model_dump(mode="json")
        if domain_enum is Domain.LAND:
            try:
                cached = await store.get_land_cache(hormuz_region.id)
                if cached is not None:
                    age_s = (
                        datetime.now(timezone.utc) - cached.fetched_at
                    ).total_seconds()
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
        snapshot = registry.get(domain_enum)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail=_error_envelope(
                    "not_found",
                    f"no active region / snapshot for {domain_enum.value}",
                ),
            )
        return snapshot.model_dump(mode="json")

    @app.post("/api/layers/{domain}/toggle")
    async def toggle_layer(domain: str, payload: _LayerToggleRequest) -> dict:
        """FR5 (api.md "POST /api/layers/{domain}/toggle"): delegate straight
        to `scheduler.set_enabled` and echo back what was requested --
        disabling stops that adapter's scheduling (zero upstream budget),
        enabling triggers an immediate fetch (scheduler.md "Enable/disable
        (FR5)")."""
        domain_enum = _coerce_domain(domain)
        await scheduler.set_enabled(domain_enum, payload.enabled)
        return {"layer": domain_enum.value, "enabled": payload.enabled}

    @app.post("/api/layers/{domain}/refresh", status_code=202)
    async def refresh_layer(domain: str) -> dict:
        """FR6 (api.md "POST /api/layers/{domain}/refresh"): fire-and-forget
        manual refresh -- results ride SSE, not the HTTP response, so a
        failed fetch (already recorded + published by the scheduler's own
        write path, #38) must never turn into a 5xx here."""
        domain_enum = _coerce_domain(domain)
        try:
            await scheduler.refresh(domain_enum)
        except Exception:
            _LOG.warning(
                "POST /api/layers/%s/refresh: refresh failed",
                domain_enum.value,
                exc_info=True,
            )
        return {"layer": domain_enum.value, "queued": True}

    @app.post("/api/refresh", status_code=202)
    async def refresh() -> dict:
        """FR6 (api.md "POST /api/refresh"): delegate to
        `scheduler.refresh_all()` and echo back exactly the enabled-layer
        list it reports queuing -- never a hardcoded domain list, so a
        disabled layer (e.g. marine) is genuinely excluded."""
        queued = await scheduler.refresh_all()
        return {"queued": [domain.value for domain in queued]}

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
