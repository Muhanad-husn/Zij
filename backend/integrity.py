"""FR9 plausibility flags (contract: design/specs/integrity.md; feature-schema.md).

Two cheap, pure flags computed post-adapter/pre-registry (scheduler.md write
path): landmask point-in-polygon (marine-on-land -> spoof-suspect) and
implausible kinematics (implied speed between consecutive reports, marine +
air). `Integrity.apply` is Features in -> Features with `integrity_flags`
appended out; no I/O at flag time (NFR3). Loading the landmask asset itself
is the one I/O step, and it happens once at `Integrity.__init__` (startup),
never inside `apply`.

Slice integrity/01-flags (issue #43). Static caveat text + active-flag
counting (`CAVEATS`) is out of scope here and lands in step
(plans/integrity/01-flags.md "Out of scope").
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import platformdirs
from shapely import STRtree
from shapely.errors import ShapelyError
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from backend.models import Domain, Feature, IntegrityFlag

_EARTH_RADIUS_M = 6371000.0

# config.md [integrity] landmask_path="" -> this default (populated once by
# scripts/fetch_landmask.py, STRUCTURE.md).
_DEFAULT_LANDMASK_PATH = (
    Path(platformdirs.user_data_dir("zij")) / "landmask" / "ne_10m_land.geojson"
)


class LandmaskError(RuntimeError):
    """Raised when the landmask asset is missing or corrupt at `Integrity`
    construction time. Fail-fast, by design: FR9's spoof check is a P0
    honesty requirement and NFR3 forbids ever shipping it silently disabled
    (design/specs/integrity.md "Failure modes")."""


@dataclass(frozen=True)
class IntegrityCfg:
    """`[integrity]` (config.md): landmask_path, max_speed_kn_marine,
    max_speed_kn_air."""

    landmask_path: str
    max_speed_kn_marine: float
    max_speed_kn_air: float


@dataclass(frozen=True)
class PrevPos:
    """One entry of the `prev: source_id -> last (lat, lon, timestamp_source)`
    map threaded into `Integrity.apply` (design/specs/integrity.md)."""

    lat: float
    lon: float
    timestamp_source: datetime | None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _resolve_landmask_path(landmask_path: str) -> Path:
    if landmask_path:
        return Path(landmask_path)
    return _DEFAULT_LANDMASK_PATH


def _load_land_geometries(path: Path) -> list[BaseGeometry]:
    """Parse a GeoJSON `FeatureCollection` of land Polygon/MultiPolygon
    geometries (design/specs/integrity.md "Load once at startup"). Raises
    `LandmaskError` for anything short of a well-formed collection -- fail
    fast rather than silently loading zero polygons (NFR3)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LandmaskError(f"landmask asset not readable at {path}: {exc}") from exc

    try:
        collection = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LandmaskError(
            f"landmask asset at {path} is not valid JSON: {exc}"
        ) from exc

    if (
        not isinstance(collection, dict)
        or collection.get("type") != "FeatureCollection"
    ):
        raise LandmaskError(
            f"landmask asset at {path} is not a GeoJSON FeatureCollection"
        )

    features: Any = collection.get("features")
    if not isinstance(features, list) or not features:
        raise LandmaskError(f"landmask asset at {path} contains no features")

    geometries: list[BaseGeometry] = []
    try:
        for feature in features:
            geometries.append(shape(feature["geometry"]))
    except (KeyError, TypeError, ShapelyError) as exc:
        raise LandmaskError(
            f"landmask asset at {path} contains an unparseable geometry: {exc}"
        ) from exc

    return geometries


class Integrity:
    """FR9 plausibility flags. Constructed once at startup (loads the
    landmask asset, fail-fast); `apply` is pure and side-effect-free."""

    def __init__(self, cfg: IntegrityCfg) -> None:
        self._cfg = cfg
        path = _resolve_landmask_path(cfg.landmask_path)
        self._land_geometries = _load_land_geometries(path)
        self._land_tree = STRtree(self._land_geometries)

    def apply(self, features: list[Feature], prev: dict[str, PrevPos]) -> list[Feature]:
        """Post-adapter, pre-registry. Appends `integrity_flags` in place and
        returns `features`. No I/O; deterministic given `(features, prev)`."""
        for feature in features:
            if feature.domain == Domain.MARINE and self._on_land(feature):
                feature.integrity_flags.append(IntegrityFlag.SPOOF_SUSPECT_ON_LAND)

            if feature.domain in (Domain.MARINE, Domain.AIR):
                self._flag_kinematics(feature, prev)

        return features

    def _on_land(self, feature: Feature) -> bool:
        point = Point(feature.lon, feature.lat)
        for index in self._land_tree.query(point):
            if self._land_geometries[index].contains(point):
                return True
        return False

    def _flag_kinematics(self, feature: Feature, prev: dict[str, PrevPos]) -> None:
        prev_pos = prev.get(feature.source_id)
        if prev_pos is None:
            return
        if feature.timestamp_source is None or prev_pos.timestamp_source is None:
            return

        dt = (feature.timestamp_source - prev_pos.timestamp_source).total_seconds()
        if dt <= 0:
            return

        dist_nm = haversine(prev_pos.lat, prev_pos.lon, feature.lat, feature.lon) / 1852
        implied_kn = dist_nm / (dt / 3600)

        threshold = (
            self._cfg.max_speed_kn_marine
            if feature.domain == Domain.MARINE
            else self._cfg.max_speed_kn_air
        )
        if implied_kn > threshold:
            feature.integrity_flags.append(IntegrityFlag.IMPLAUSIBLE_KINEMATICS)
