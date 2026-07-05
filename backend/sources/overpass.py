"""Overpass PollAdapter (spec: design/specs/overpass.md).

Slice overpass-adapter/01 (issue #15) implements the network fetch + parse
path: the six whitelisted Overpass QL class queries (§6.3), sequential
per-class fetch with mirror rotation + exponential backoff on 429/504/
timeout, `elements` -> `Feature` parsing (point/linestring/polygon), dedup by
`source_id` (first wins across classes), and `osm3s.timestamp_osm_base`
capture (oldest across responses) stamped as every feature's and the
snapshot's `timestamp_source`.

Geometry simplification (Douglas-Peucker via shapely) and the <=5000
deterministic drop priority are explicitly OUT of scope for this slice
(deferred to overpass-adapter/02, design/specs/overpass.md "Geometry
simplification"); `fetch()` here returns the parsed features un-simplified.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel

from backend.models import (
    Domain,
    Feature,
    FeatureStatus,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.sources.base import ParseError, PollAdapter, Region, UpstreamError

# §6.3 whitelist -- the six feature-class queries. `{bbox}` is substituted
# with "south,west,north,east" (Overpass QL bbox order) built from
# `region.bbox` ([west, south, east, north], config.md). `out center` yields
# a representative point for node/area classes; `out geom` returns inline
# node coordinates (needed for LineString geometry) for the two ways-only
# classes.
_QUERY_TEMPLATES: tuple[str, ...] = (
    'node["barrier"="border_control"]({bbox});out;',
    '(node["aeroway"="aerodrome"]({bbox});'
    'way["aeroway"="aerodrome"]({bbox}););out center;',
    '(node["harbour"]({bbox});way["harbour"]({bbox});'
    'way["landuse"="port"]({bbox}););out center;',
    '(node["railway"~"^(station|yard)$"]({bbox});'
    'way["railway"~"^(station|yard)$"]({bbox}););out center;',
    'way["highway"~"^(motorway|trunk|primary)$"]({bbox});out geom;',
    'way["railway"="rail"]({bbox});out geom;',
)

# Be kind to public mirrors (§6.3/§12): sequential per-class fetch, not
# parallel -- a parallel burst to one mirror is exactly what triggers
# throttling.
_CLASS_DELAY_S = 0.5


class OverpassCfg(BaseModel):
    """`[overpass]` table + `[layers.land]` (config.md). Constructed as
    `OverpassCfg(**cfg.overpass, **cfg.layers["land"].model_dump())`."""

    # [overpass]
    mirrors: list[str]
    timeout_s: float
    maxsize_bytes: int
    backoff_base_s: float
    backoff_max_s: float
    max_attempts: int

    # [layers.land] (LayerCfg.model_dump())
    enabled: bool = True
    cadence_s: int
    cadence_floor_s: int
    stale_multiplier: int = 2
    custom_bbox_cap_sq_deg: float
    deemphasize_after_s: int | None = None
    drop_after_s: int | None = None
    simplify_tolerance_deg: float | None = None
    max_rendered_features: int | None = None


def _polygon_centroid(vertices: list[dict[str, float]]) -> tuple[float, float]:
    """Area-weighted centroid of a closed ring (`vertices` is a list of
    `{"lat":..., "lon":...}` dicts, first == last, Overpass `out geom`
    shape). Falls back to the arithmetic mean of the distinct vertices when
    the ring encloses ~zero area (degenerate ring). Returns `(lat, lon)`."""
    points = [(v["lon"], v["lat"]) for v in vertices]
    area = 0.0
    cx = 0.0
    cy = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2.0
    if abs(area) < 1e-12:
        distinct = points[:-1] or points
        lons = [p[0] for p in distinct]
        lats = [p[1] for p in distinct]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    cx /= 6.0 * area
    cy /= 6.0 * area
    return cy, cx


class OverpassAdapter(PollAdapter):
    domain = Domain.LAND
    source = "overpass"

    def __init__(self, cfg: OverpassCfg):
        self._cfg = cfg
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Open the shared AsyncClient (idempotent). Overpass has no auth,
        so there is no token to prefetch."""
        if self._client is None:
            self._client = httpx.AsyncClient()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, region: Region) -> LayerSnapshot:
        """Run the six whitelisted class queries over `region.bbox`
        sequentially, parse+dedup their `elements` into `Feature`s, and
        stamp every feature + the snapshot with the oldest `osm_base` seen
        across responses (design/specs/overpass.md "osm_base capture
        (FR4)")."""
        if self._client is None:
            self._client = httpx.AsyncClient()

        now = datetime.now(timezone.utc)
        west, south, east, north = region.bbox
        bbox = f"{south},{west},{north},{east}"

        class_bodies: list[dict[str, Any]] = []
        for index, template in enumerate(_QUERY_TEMPLATES):
            if index > 0:
                await asyncio.sleep(_CLASS_DELAY_S)
            class_bodies.append(await self._fetch_class(template.format(bbox=bbox)))

        osm_base = min(self._parse_osm_base(body) for body in class_bodies)

        features: list[Feature] = []
        seen_source_ids: set[str] = set()
        for body in class_bodies:
            for element in self._parse_elements(body):
                source_id = self._source_id(element)
                if source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)
                features.append(
                    self._feature_from_element(element, source_id, now, osm_base)
                )

        return LayerSnapshot(
            meta=LayerSnapshotMeta(
                layer=Domain.LAND,
                region_id=region.id,
                status=LayerStatus.LIVE,
                timestamp_fetched=now,
                timestamp_source=osm_base,
                cadence_s=self._cfg.cadence_s,
                stale_after_s=self._cfg.cadence_s * self._cfg.stale_multiplier,
                feature_count=len(features),
            ),
            features=features,
        )

    async def _fetch_class(self, query: str) -> dict[str, Any]:
        """POST one class query, rotating `cfg.mirrors` and backing off
        exponentially on 429/504/timeout (design/specs/overpass.md
        "Partitioning + mirror strategy"). Other 5xx / transport errors
        surface immediately as `UpstreamError` (not mirror/rate-limit
        conditions a retry would fix). Exhausting `cfg.max_attempts` across
        mirrors -> `UpstreamError`."""
        header = (
            f"[out:json][timeout:{int(self._cfg.timeout_s)}]"
            f"[maxsize:{self._cfg.maxsize_bytes}];"
        )
        payload = header + query
        assert self._client is not None

        mirror_index = 0
        last_status: int | None = None
        for attempt in range(self._cfg.max_attempts):
            mirror = self._cfg.mirrors[mirror_index % len(self._cfg.mirrors)]
            try:
                response = await self._client.post(
                    mirror,
                    data={"data": payload},
                    timeout=self._cfg.timeout_s + 30,
                )
            except httpx.TimeoutException:
                mirror_index += 1
                await self._backoff(attempt)
                continue
            except httpx.TransportError as exc:
                raise UpstreamError("overpass request transport error") from exc

            status = response.status_code
            if status in (429, 504):
                last_status = status
                mirror_index += 1
                await self._backoff(attempt)
                continue
            if status >= 500 or status < 200 or status >= 300:
                raise UpstreamError(f"overpass endpoint returned {status}")

            try:
                return response.json()
            except ValueError as exc:
                raise ParseError("overpass response was not valid JSON") from exc

        detail = f" (last status {last_status})" if last_status is not None else ""
        raise UpstreamError(
            f"overpass exhausted {self._cfg.max_attempts} attempts across mirrors"
            + detail
        )

    async def _backoff(self, attempt: int) -> None:
        delay = min(
            self._cfg.backoff_max_s, self._cfg.backoff_base_s * 2**attempt
        )
        await asyncio.sleep(delay)

    def _parse_osm_base(self, body: dict[str, Any]) -> datetime:
        try:
            raw = body["osm3s"]["timestamp_osm_base"]
        except (KeyError, TypeError) as exc:
            raise ParseError(
                "overpass response missing osm3s.timestamp_osm_base"
            ) from exc
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ParseError(
                "overpass response osm3s.timestamp_osm_base was not ISO-parseable"
            ) from exc

    def _parse_elements(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            elements = body["elements"]
        except (KeyError, TypeError) as exc:
            raise ParseError("overpass response missing 'elements' array") from exc
        if not isinstance(elements, list):
            raise ParseError("overpass response 'elements' was not a list")
        return elements

    def _source_id(self, element: dict[str, Any]) -> str:
        try:
            return f"{element['type']}/{element['id']}"
        except (KeyError, TypeError) as exc:
            raise ParseError("overpass element missing type/id") from exc

    def _feature_from_element(
        self,
        element: dict[str, Any],
        source_id: str,
        now: datetime,
        osm_base: datetime,
    ) -> Feature:
        try:
            tags: dict[str, Any] = element.get("tags", {}) or {}
            label = tags.get("name")

            if "center" in element:
                # `out center` result (node/area classes): representative
                # point, no explicit geometry.
                lat = element["center"]["lat"]
                lon = element["center"]["lon"]
                geometry_type = GeometryType.POINT
                geometry = None
            elif "geometry" in element:
                # `out geom` result: inline node coordinates.
                vertices = element["geometry"]
                coordinates = [[v["lon"], v["lat"]] for v in vertices]
                if len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
                    # Closed way -> POLYGON + centroid (area classes that
                    # come back with full geometry rather than a center).
                    geometry_type = GeometryType.POLYGON
                    geometry = {"type": "Polygon", "coordinates": [coordinates]}
                    lat, lon = _polygon_centroid(vertices)
                else:
                    geometry_type = GeometryType.LINESTRING
                    geometry = {"type": "LineString", "coordinates": coordinates}
                    midpoint = vertices[len(vertices) // 2]
                    lat, lon = midpoint["lat"], midpoint["lon"]
            else:
                # Bare node (`out;`): top-level lat/lon.
                lat = element["lat"]
                lon = element["lon"]
                geometry_type = GeometryType.POINT
                geometry = None

            return Feature(
                domain=Domain.LAND,
                source=self.source,
                source_id=source_id,
                label=label,
                lat=lat,
                lon=lon,
                geometry_type=geometry_type,
                geometry=geometry,
                timestamp_source=osm_base,
                timestamp_fetched=now,
                position_age_s=(now - osm_base).total_seconds(),
                status=FeatureStatus.LIVE,
                attrs=tags,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ParseError(f"overpass element {source_id} failed parsing: {exc}") from exc
