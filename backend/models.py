"""Common feature schema (contract: design/contracts/feature-schema.md).

Implements PRD §10 "Common feature schema" and FR7/FR8/FR9/FR11 (ADR-1: Pydantic
v2). This module is the single validated vocabulary consumed by every adapter,
the API layer, and storage. Transcribed verbatim from the frozen contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Domain(str, Enum):
    AIR = "air"
    MARINE = "marine"
    LAND = "land"


class GeometryType(str, Enum):
    POINT = "point"
    LINESTRING = "linestring"
    POLYGON = "polygon"


class FeatureStatus(str, Enum):
    """Per-feature freshness (distinct from per-layer LayerStatus)."""

    LIVE = "live"
    STALE = "stale"  # position_age_s exceeds the layer's configured deemphasize_after_s at snapshot time
    CACHED_FALLBACK = "cached-fallback"  # came from fallback_snapshots (FR8)


class IntegrityFlag(str, Enum):
    """FR9 cheap plausibility flags, computed at render time. Open enum: add
    conservatively — new flags are a UI change, not a pipeline (NFR2/NFR3)."""

    SPOOF_SUSPECT_ON_LAND = "spoof_suspect_on_land"  # marine point on land polygon
    IMPLAUSIBLE_KINEMATICS = "implausible_kinematics"  # >120 kn marine / >Mach 3 air


class LayerStatus(str, Enum):
    """Per-layer badge status (FR7). Owned and set by the scheduler, never by an
    adapter (see adapter-interface.md#status-ownership)."""

    LIVE = "live"
    STALE = "stale"  # source data older than 2x cadence (FR7)
    LOADING = "loading"
    RATE_LIMITED = "rate-limited"  # 429; carries retry_after_s
    ERROR = "error"  # last fetch failed, no warm cache
    CACHED_FALLBACK = "cached-fallback"  # serving FR8 fallback snapshot
    RECONNECTING = (
        "reconnecting"  # marine stream only (FR3); UI treats as loading-family
    )


def _reject_naive_datetime(value: datetime | None) -> datetime | None:
    """Shared validator: every timestamp must be timezone-aware UTC (NFR6).

    Naive datetimes are ambiguous and are rejected outright rather than
    coerced. Aware datetimes in a non-UTC offset are normalized to UTC
    (lossless, since the offset is known) so the wire format is always
    ``Z``. Aware UTC datetimes pass through unchanged.
    """
    if value is None:
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware (no naive datetimes)")
    if value.utcoffset() != timezone.utc.utcoffset(None):
        return value.astimezone(timezone.utc)
    return value


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    domain: Domain
    source: str  # "opensky" | "aisstream" | "overpass"
    source_id: str  # ICAO24 (air) | MMSI (marine) | OSM type/id (land)
    label: str | None = None  # callsign | vessel name | OSM name; may be absent

    # Representative point — ALWAYS present (line/polygon carry a centroid/vertex).
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    geometry_type: GeometryType
    # GeoJSON geometry object for line/polygon; None for points (lat/lon suffice).
    geometry: dict[str, Any] | None = None

    timestamp_source: (
        datetime | None
    )  # source's own time (time_position / AIS ts / osm_base)
    timestamp_fetched: datetime  # when Zij fetched/snapshotted it (UTC)
    position_age_s: (
        float | None
    )  # now - timestamp_source, seconds; None if no source ts

    status: FeatureStatus = FeatureStatus.LIVE
    integrity_flags: list[IntegrityFlag] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(
        default_factory=dict
    )  # domain-specific, see Units table

    # In-memory only. Excluded from model_dump()/JSON by default (exclude=True).
    # Reachable solely via the raw-payload inspection endpoint (FR11).
    raw_payload: dict[str, Any] | None = Field(default=None, exclude=True, repr=False)

    @field_validator("timestamp_source", "timestamp_fetched")
    @classmethod
    def _validate_utc_aware(cls, value: datetime | None) -> datetime | None:
        return _reject_naive_datetime(value)


class LayerSnapshotMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: Domain
    region_id: str  # predefined id or "custom:<hash>"
    status: LayerStatus
    timestamp_fetched: datetime | None  # last successful fetch/snapshot (UTC)
    timestamp_source: datetime | None  # representative source ts: osm_base (land),
    # newest/representative report time (air/marine)
    cadence_s: int  # configured display cadence (config.md)
    stale_after_s: int  # 2 x cadence_s (FR7)
    feature_count: int
    retry_after_s: float | None = None  # set when status == rate-limited
    detail: str | None = None  # human message (error text, "reconnecting", etc.)

    @field_validator("timestamp_source", "timestamp_fetched")
    @classmethod
    def _validate_utc_aware(cls, value: datetime | None) -> datetime | None:
        return _reject_naive_datetime(value)


class LayerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: LayerSnapshotMeta
    features: list[Feature]
