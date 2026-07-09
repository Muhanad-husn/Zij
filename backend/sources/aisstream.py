"""aisstream.io StreamAdapter (spec: design/specs/aisstream.md).

Slice sources-marine/01 (issue #47) implements the core of the adapter: the
websocket connect + subscribe, the read loop's PositionReport/ShipStaticData
handling into the `_table`/`_prev_pos` latest-position projection, and the
synchronous `snapshot()` aging pass. Reconnect/backoff, the eviction sweep,
and a full `set_region` re-subscribe/clear are slice 02 (out of scope here);
`set_region`/`stop` provide the minimal pre-connect bootstrap behavior this
slice needs without breaking the `StreamAdapter` ABC contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import websockets
from pydantic import BaseModel

from backend.config import Secrets
from backend.models import (
    Domain,
    Feature,
    FeatureStatus,
    GeometryType,
    LayerSnapshot,
    LayerSnapshotMeta,
    LayerStatus,
)
from backend.sources.base import Region, StreamAdapter

logger = logging.getLogger(__name__)

# aisstream.md "Message handling": TrueHeading sentinel meaning "not
# available" -- must be dropped to None, never rendered as a real heading.
_HEADING_NOT_AVAILABLE = 511


class AisStreamCfg(BaseModel):
    """`[aisstream]` + `[layers.marine]` (config.md). Constructed as
    `AisStreamCfg(**cfg.aisstream, **cfg.layers["marine"].model_dump())`,
    mirroring `OpenSkyCfg`'s established shape."""

    # [aisstream]
    ws_url: str
    reconnect_base_s: float = 2.0
    reconnect_max_s: float = 60.0

    # [layers.marine] (LayerCfg.model_dump())
    enabled: bool = True
    cadence_s: int
    cadence_floor_s: int
    stale_multiplier: int = 2
    custom_bbox_cap_sq_deg: float
    deemphasize_after_s: int | None = None
    drop_after_s: int | None = None
    # Unused by marine, but LayerCfg.model_dump() always carries these keys.
    simplify_tolerance_deg: float | None = None
    max_rendered_features: int | None = None


@dataclass
class _Entry:
    feature: Feature
    last_heard: datetime
    name: str | None = None
    callsign: str | None = None


def _parse_aisstream_time_utc(value: str) -> datetime:
    """Parse aisstream's non-ISO `MetaData.time_utc` -- Go's
    `time.Time.String()` format: `"YYYY-MM-DD HH:MM:SS[.fraction] +0000 UTC"`
    -- into a UTC-aware datetime.

    Go's `time.Time.String()` prints a *variable-length* fractional-seconds
    component with trailing zeros trimmed: no `.` at all when the time lands
    exactly on the second, and anywhere from 1 to 9 digits (nanosecond
    precision) otherwise. Python's `%f` directive only accepts 1-6 digits,
    so the fraction is parsed out manually and normalized to exactly 6
    digits (padded or truncated) before handing off to `strptime`.
    """
    # Strip the trailing " UTC" zone name; the offset "+0000" plus "%z"
    # already pins the timezone, and datetime.strptime doesn't accept a
    # literal "UTC" token after the numeric offset.
    text = value.strip()
    if text.endswith(" UTC"):
        text = text[: -len(" UTC")]

    # Split off the trailing " +0000" offset, then the optional
    # ".fraction" from the "YYYY-MM-DD HH:MM:SS[.fraction]" datetime part,
    # e.g. "2026-07-09 11:58:00.123456789 +0000" -> datetime part
    # "2026-07-09 11:58:00.123456789" + offset "+0000".
    datetime_part, sep, offset = text.rpartition(" ")
    seconds_part, dot, fraction = datetime_part.partition(".")
    if dot:
        # Pad short fractions (e.g. 3 digits) and truncate long ones (up to
        # 9 nanosecond digits) to exactly the 6 digits %f requires.
        fraction = (fraction + "000000")[:6]
        datetime_part = f"{seconds_part}.{fraction}"
    else:
        datetime_part = f"{seconds_part}.000000"
    text = f"{datetime_part} {offset}" if sep else datetime_part

    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f %z")
    return parsed.astimezone(timezone.utc)


class AisStreamAdapter(StreamAdapter):
    domain = Domain.MARINE
    source = "aisstream"

    def __init__(self, cfg: AisStreamCfg, secrets: Secrets) -> None:
        self._cfg = cfg
        self._secrets = secrets
        self._table: dict[str, _Entry] = {}
        self._prev_pos: dict[str, tuple[float, float, datetime | None]] = {}
        self._region: Region | None = None
        self._ws: Any = None
        self._read_task: asyncio.Task[None] | None = None
        self._connected: bool = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def set_region(self, region: Region) -> None:
        """Pre-connect bootstrap: record the region to subscribe on the next
        `start()`. Mid-stream re-subscribe + table clear is slice 02."""
        self._region = region

    async def start(self) -> None:
        """Connect `cfg.ws_url`, send the subscribe payload immediately, and
        launch the read loop as `_read_task`. Returns once subscribed."""
        self._ws = await websockets.connect(self._cfg.ws_url)
        await self._subscribe()
        self._connected = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        """Close the websocket, cancel the read loop."""
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self._connected = False

    async def _subscribe(self) -> None:
        payload = self._build_subscribe_payload()
        await self._ws.send(json.dumps(payload))

    def _build_subscribe_payload(self) -> dict[str, Any]:
        bounding_boxes: list[list[list[float]]] = []
        if self._region is not None:
            west, south, east, north = self._region.bbox
            bounding_boxes = [[[south, west], [north, east]]]
        return {
            "APIKey": self._secrets.aisstream_api_key,
            "BoundingBoxes": bounding_boxes,
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    self._handle_message(raw)
                except Exception:
                    # Malformed single message -> skip + log (aisstream.md
                    # "Failure modes"); never let one bad frame kill the
                    # stream.
                    logger.exception("aisstream: failed to handle message")
        except asyncio.CancelledError:
            raise
        except Exception:
            self._connected = False
            logger.exception("aisstream: read loop terminated")

    def _handle_message(self, raw: str | bytes) -> None:
        message = json.loads(raw)
        message_type = message.get("MessageType")
        if message_type == "PositionReport":
            self._handle_position_report(message)
        elif message_type == "ShipStaticData":
            self._handle_ship_static_data(message)
        # Unknown message types are silently ignored (not subscribed to, but
        # tolerate anyway).

    def _handle_position_report(self, message: dict[str, Any]) -> None:
        meta = message["MetaData"]
        mmsi = str(meta["MMSI"])
        report = message["Message"]["PositionReport"]

        timestamp_source = _parse_aisstream_time_utc(meta["time_utc"])
        now = datetime.now(timezone.utc)

        existing = self._table.get(mmsi)
        if existing is not None:
            # Before overwriting, copy the OUTGOING (prior) fix into
            # _prev_pos[MMSI] -- FR9 kinematics input (aisstream.md "Message
            # handling").
            self._prev_pos[mmsi] = (
                existing.feature.lat,
                existing.feature.lon,
                existing.feature.timestamp_source,
            )

        heading = report.get("TrueHeading")
        if heading == _HEADING_NOT_AVAILABLE:
            heading = None

        name = existing.name if existing is not None else None
        callsign = existing.callsign if existing is not None else None
        attrs: dict[str, Any] = {}
        if existing is not None:
            attrs = dict(existing.feature.attrs)
        attrs.update(
            {
                "sog_kn": report.get("Sog"),
                "cog_deg": report.get("Cog"),
                "heading_deg": heading,
                "nav_status": report.get("NavigationalStatus"),
            }
        )

        feature = Feature(
            domain=Domain.MARINE,
            source=self.source,
            source_id=mmsi,
            label=name or None,
            lat=report["Latitude"],
            lon=report["Longitude"],
            geometry_type=GeometryType.POINT,
            geometry=None,
            timestamp_source=timestamp_source,
            timestamp_fetched=now,
            position_age_s=None,
            status=FeatureStatus.LIVE,
            attrs=attrs,
            raw_payload=message,
        )

        self._table[mmsi] = _Entry(
            feature=feature,
            last_heard=now,
            name=name,
            callsign=callsign,
        )

    def _handle_ship_static_data(self, message: dict[str, Any]) -> None:
        meta = message["MetaData"]
        mmsi = str(meta["MMSI"])
        entry = self._table.get(mmsi)
        if entry is None:
            # Does not create an entry on its own (aisstream.md "Message
            # handling"): static data ≠ a position fix.
            return

        static = message["Message"]["ShipStaticData"]
        name = meta.get("ShipName") or static.get("Name") or None
        callsign = static.get("CallSign") or None
        ship_type = static.get("Type")

        entry.name = name
        entry.callsign = callsign
        attrs = dict(entry.feature.attrs)
        attrs["ship_type"] = ship_type
        entry.feature = entry.feature.model_copy(
            update={"label": name or None, "attrs": attrs}
        )

    def snapshot(self) -> LayerSnapshot:
        """SYNCHRONOUS point-in-time copy of `_table`, applying the
        de-emphasis/drop aging windows (FR3). No I/O; never raises."""
        now = datetime.now(timezone.utc)
        deemphasize_after_s = self._cfg.deemphasize_after_s
        drop_after_s = self._cfg.drop_after_s

        features: list[Feature] = []
        newest_source_ts: datetime | None = None

        for entry in self._table.values():
            timestamp_source = entry.feature.timestamp_source
            position_age_s = (
                (now - timestamp_source).total_seconds()
                if timestamp_source is not None
                else None
            )

            if (
                position_age_s is not None
                and drop_after_s is not None
                and position_age_s > drop_after_s
            ):
                continue

            status = FeatureStatus.LIVE
            if (
                position_age_s is not None
                and deemphasize_after_s is not None
                and position_age_s > deemphasize_after_s
            ):
                status = FeatureStatus.STALE

            feature = entry.feature.model_copy(
                update={
                    "position_age_s": position_age_s,
                    "status": status,
                    "attrs": dict(entry.feature.attrs),
                }
            )
            features.append(feature)

            if timestamp_source is not None and (
                newest_source_ts is None or timestamp_source > newest_source_ts
            ):
                newest_source_ts = timestamp_source

        region_id = self._region.id if self._region is not None else ""

        return LayerSnapshot(
            meta=LayerSnapshotMeta(
                layer=Domain.MARINE,
                region_id=region_id,
                status=LayerStatus.LIVE,
                timestamp_fetched=now,
                timestamp_source=newest_source_ts,
                cadence_s=self._cfg.cadence_s,
                stale_after_s=2 * self._cfg.cadence_s,
                feature_count=len(features),
            ),
            features=features,
        )
