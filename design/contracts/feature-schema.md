# Contract — Common Feature Schema

Implements PRD §10 "Common feature schema" and FR7/FR8/FR9/FR11. This is the exact `backend/models.py` model layer; implementation copies it verbatim. Uses Pydantic v2 ([ADR-1](../docs/DECISIONS.md#adr-1--pydantic-v2)). Consumed by [adapter-interface.md](adapter-interface.md), [api.md](api.md), [storage.md](storage.md).

## Conventions (load-bearing)

- **Time:** every timestamp is timezone-aware UTC `datetime` (NFR6). Serialized as ISO-8601 with `Z`. No naive datetimes, ever.
- **Coordinates:** WGS84 decimal degrees. `lat` ∈ [-90, 90], `lon` ∈ [-180, 180]. GeoJSON `geometry` uses `[lon, lat]` order (RFC 7946, [ADR-11](../docs/DECISIONS.md#adr-11--geometry-wire-format-geojson)).
- **Units — keep source-native, unit encoded in the attr key** (decision below). No cross-domain normalization.
- **`raw_payload`** is in-memory only; excluded from all normal serialization ([§ raw_payload handling](#raw_payload-handling)).

### Units decision

Normalizing would be lossy and would fight the popups, which show what the source broadcasts (FR2, FR3). So **units are kept source-native and named in the attr key**:

| Domain | attr key | unit | source |
|---|---|---|---|
| air | `altitude_m` (baro), `geo_altitude_m` | metres | OpenSky |
| air | `velocity_ms` | m/s | OpenSky `velocity` |
| air | `vertical_rate_ms` | m/s | OpenSky |
| air | `true_track_deg` | degrees | OpenSky |
| marine | `sog_kn` | knots | AIS SOG |
| marine | `cog_deg`, `heading_deg` | degrees | AIS |
| land | OSM tags verbatim | — | Overpass |

The integrity kinematics check (FR9) converts internally (Mach 3 for air using `velocity_ms`; 120 kn for marine using `sog_kn`) but stored values stay native. Any UI unit conversion is a frontend concern.

## Enums

```python
from __future__ import annotations
from enum import Enum


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
    STALE = "stale"                # position_age_s exceeds the layer's configured deemphasize_after_s at snapshot time
    CACHED_FALLBACK = "cached-fallback"  # came from fallback_snapshots (FR8)


class IntegrityFlag(str, Enum):
    """FR9 cheap plausibility flags, computed at render time. Open enum: add
    conservatively — new flags are a UI change, not a pipeline (NFR2/NFR3)."""
    SPOOF_SUSPECT_ON_LAND = "spoof_suspect_on_land"     # marine point on land polygon
    IMPLAUSIBLE_KINEMATICS = "implausible_kinematics"   # >120 kn marine / >Mach 3 air


class LayerStatus(str, Enum):
    """Per-layer badge status (FR7). Owned and set by the scheduler, never by an
    adapter (see adapter-interface.md#status-ownership)."""
    LIVE = "live"
    STALE = "stale"                 # source data older than 2x cadence (FR7)
    LOADING = "loading"
    RATE_LIMITED = "rate-limited"   # 429; carries retry_after_s
    ERROR = "error"                 # last fetch failed, no warm cache
    CACHED_FALLBACK = "cached-fallback"  # serving FR8 fallback snapshot
    RECONNECTING = "reconnecting"   # marine stream only (FR3); UI treats as loading-family
```

### LayerStatus note

FR7 enumerates six states; FR3 additionally requires marine to show **`reconnecting`** on websocket drop. We include it as a seventh, **marine-stream-only** state. For badge coloring the frontend groups it with the `loading` family. Downstream UI specs must handle seven values, not six — see [ARCHITECTURE §5](../docs/ARCHITECTURE.md#5-failure-isolation-fr10-and-the-layer-status-state-machine).

## Feature model

```python
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    domain: Domain
    source: str                       # "opensky" | "aisstream" | "overpass"
    source_id: str                    # ICAO24 (air) | MMSI (marine) | OSM type/id (land)
    label: str | None = None          # callsign | vessel name | OSM name; may be absent

    # Representative point — ALWAYS present (line/polygon carry a centroid/vertex).
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    geometry_type: GeometryType
    # GeoJSON geometry object for line/polygon; None for points (lat/lon suffice).
    geometry: dict[str, Any] | None = None

    timestamp_source: datetime | None  # source's own time (time_position / AIS ts / osm_base)
    timestamp_fetched: datetime        # when Zij fetched/snapshotted it (UTC)
    position_age_s: float | None       # now - timestamp_source, seconds; None if no source ts

    status: FeatureStatus = FeatureStatus.LIVE
    integrity_flags: list[IntegrityFlag] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)  # domain-specific, see Units table

    # In-memory only. Excluded from model_dump()/JSON by default (exclude=True).
    # Reachable solely via the raw-payload inspection endpoint (FR11).
    raw_payload: dict[str, Any] | None = Field(default=None, exclude=True, repr=False)
```

### Nullability rules per domain

| field | air | marine | land |
|---|---|---|---|
| `label` | callsign, often null | name, often null (many vessels omit) | OSM `name`, may be null |
| `timestamp_source` | `time_position`, may be null (Mode S gap) | AIS report time, present | `osm_base`, present |
| `position_age_s` | null iff `timestamp_source` null | present | present (from `osm_base`; large by nature) |
| `geometry` | null (point) | null (point) | present for line/polygon; null for point (port node, aerodrome node) |
| `attrs.altitude_m` | may be null (no altitude) | n/a | n/a |
| `attrs.sog_kn`/`cog_deg` | n/a | may be null (not broadcast) | n/a |

### geometry

- **Points** (all air, all marine, some land nodes): `geometry_type = POINT`, `geometry = None`, position in `lat`/`lon`.
- **Land ways/areas:** `geometry_type = LINESTRING | POLYGON`, `geometry =` GeoJSON object, and `lat`/`lon` = representative point (centroid for polygon, midpoint vertex for line) for label placement and clustering. This keeps `lat`/`lon` non-null across the whole schema (flat contract, FR3).

### raw_payload handling

`raw_payload` holds the untouched upstream record (OpenSky state array, AIS message dict, Overpass element). It exists so FR11's popup "raw payload inspection" works, but it must never bloat SSE frames or SQLite rows.

- **Wire/SSE:** `Field(exclude=True)` drops it from every `model_dump()` / `model_dump_json()` → SSE `snapshot` events and REST snapshots never carry it.
- **Registry:** the in-memory snapshot registry holds full `Feature` objects **with** `raw_payload` populated.
- **SQLite:** `fallback_snapshots` persists `model_dump_json()` → automatically excludes `raw_payload` (storage discipline, NFR2; [storage.md](storage.md)).
- **Inspection endpoint:** [`GET /api/features/{domain}/{source_id}/raw`](api.md#get-apifeaturesdomainsource_idraw) reads the live registry and returns `feature.raw_payload` explicitly (bypassing the exclude). If the feature has rotated out, returns 404.

## LayerSnapshot & metadata

What the API and SSE actually carry (one per layer).

```python
class LayerSnapshotMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: Domain
    region_id: str                    # predefined id or "custom:<hash>"
    status: LayerStatus
    timestamp_fetched: datetime | None  # last successful fetch/snapshot (UTC)
    timestamp_source: datetime | None   # representative source ts: osm_base (land),
                                        # newest/representative report time (air/marine)
    cadence_s: int                    # configured display cadence (config.md)
    stale_after_s: int                # 2 x cadence_s (FR7)
    feature_count: int
    retry_after_s: float | None = None  # set when status == rate-limited
    detail: str | None = None           # human message (error text, "reconnecting", etc.)


class LayerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: LayerSnapshotMeta
    features: list[Feature]
```

`LayerSnapshot` is the return type of every adapter ([adapter-interface.md](adapter-interface.md)), the payload of the SSE `snapshot` event, and the body of `GET /api/layers/{domain}/snapshot` ([api.md](api.md)). `meta` alone is the payload of the SSE `layer_status` event.

## Wire examples

### Air (OpenSky) — SSE `snapshot` data, one feature shown

```json
{
  "meta": {
    "layer": "air", "region_id": "hormuz", "status": "live",
    "timestamp_fetched": "2026-07-05T09:12:03Z",
    "timestamp_source": "2026-07-05T09:11:58Z",
    "cadence_s": 600, "stale_after_s": 1200, "feature_count": 1,
    "retry_after_s": null, "detail": null
  },
  "features": [{
    "domain": "air", "source": "opensky", "source_id": "896451",
    "label": "IRA655", "lat": 26.61, "lon": 56.27,
    "geometry_type": "point", "geometry": null,
    "timestamp_source": "2026-07-05T09:11:58Z",
    "timestamp_fetched": "2026-07-05T09:12:03Z",
    "position_age_s": 5.0, "status": "live", "integrity_flags": [],
    "attrs": {
      "altitude_m": 10668.0, "geo_altitude_m": 10820.0,
      "velocity_ms": 231.5, "vertical_rate_ms": 0.0,
      "true_track_deg": 118.4, "position_source": "ADS-B", "on_ground": false
    }
  }]
}
```

### Marine (aisstream) — one feature with a spoof flag

```json
{
  "domain": "marine", "source": "aisstream", "source_id": "422012345",
  "label": "SHINE STAR", "lat": 27.15, "lon": 56.02,
  "geometry_type": "point", "geometry": null,
  "timestamp_source": "2026-07-05T09:11:40Z",
  "timestamp_fetched": "2026-07-05T09:12:00Z",
  "position_age_s": 20.0, "status": "live",
  "integrity_flags": ["spoof_suspect_on_land"],
  "attrs": {
    "sog_kn": 0.1, "cog_deg": 341.0, "heading_deg": 340,
    "nav_status": "under way using engine", "ship_type": "tanker"
  }
}
```

### Land (Overpass) — a primary road (LineString) and a port node (point)

```json
{
  "domain": "land", "source": "overpass", "source_id": "way/23895671",
  "label": "Bandar Abbas Coastal Highway", "lat": 27.18, "lon": 56.31,
  "geometry_type": "linestring",
  "geometry": {
    "type": "LineString",
    "coordinates": [[56.28, 27.16], [56.31, 27.18], [56.34, 27.20]]
  },
  "timestamp_source": "2026-07-04T00:00:00Z",
  "timestamp_fetched": "2026-07-05T02:00:11Z",
  "position_age_s": 118211.0, "status": "live", "integrity_flags": [],
  "attrs": {"highway": "primary", "ref": "A9", "surface": "asphalt"}
}
```

```json
{
  "domain": "land", "source": "overpass", "source_id": "node/998811",
  "label": "Shahid Rajaee Port", "lat": 27.10, "lon": 56.06,
  "geometry_type": "point", "geometry": null,
  "timestamp_source": "2026-07-04T00:00:00Z",
  "timestamp_fetched": "2026-07-05T02:00:11Z",
  "position_age_s": 118211.0, "status": "live", "integrity_flags": [],
  "attrs": {"harbour": "yes", "landuse": "port"}
}
```
