"""In-process event bus (spec: design/specs/scheduler.md "Write path" step 5;
design/contracts/api.md "## SSE").

`EventBus` is the fan-out seam between the scheduler's write path and every
connected SSE client (`GET /api/events`, api-core/01). Publishing stays
synchronous (scheduler.md "Write path" step 5 reads only
`events.publish_snapshot(snap)`, no `await`, unlike step 6's `await
store.put_fallback(snap)`); each publish call fans the event out to every
subscriber's bounded, non-blocking queue, so a slow or disconnected client
can never stall the publisher or other subscribers (a full queue drops its
oldest item to make room for the new one; a subscriber that can't even
accept the just-freed slot is skipped for that publish, not awaited).

`raw_payload` never rides a published snapshot -- `Feature.raw_payload` is
declared `exclude=True` (models.py), so any `model_dump(mode="json")` of a
published `LayerSnapshot` already drops it; this module does no extra
stripping.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

from backend.models import LayerSnapshot, LayerSnapshotMeta

# Bounded so a stalled subscriber's queue can't grow without limit; small
# enough to bound memory, generous enough that a brief stall doesn't drop
# events under normal cadences.
_DEFAULT_QUEUE_MAXSIZE = 100


class EventBus:
    """In-process pub/sub fan-out. `subscribe()` returns a per-subscriber
    `asyncio.Queue` of `{"event": ..., "data": ...}` items (`data` already
    JSON-serializable via `model_dump(mode="json")`); `unsubscribe()` drops
    it on disconnect."""

    def __init__(self, *, queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE) -> None:
        self._queue_maxsize = queue_maxsize
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> "asyncio.Queue[dict[str, Any]]":
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._queue_maxsize
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict[str, Any]]") -> None:
        self._subscribers.discard(queue)

    def _fan_out(self, event: str, data: dict[str, Any]) -> None:
        item = {"event": event, "data": data}
        for queue in list(self._subscribers):
            self._offer(queue, item)

    @staticmethod
    def _offer(queue: "asyncio.Queue[dict[str, Any]]", item: dict[str, Any]) -> None:
        """Non-blocking put that never lets a full/broken subscriber stall
        the publisher: on a full queue, drop the oldest item to make room."""
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                # Still full (concurrent producer) -- skip this subscriber
                # for this publish rather than block.
                pass

    def publish_snapshot(self, snap: LayerSnapshot) -> None:
        """Publish a full snapshot (SSE `event: snapshot`, api.md "## SSE")."""
        self._fan_out("snapshot", snap.model_dump(mode="json"))

    def publish_layer_status(self, meta: LayerSnapshotMeta) -> None:
        """Publish a status/timestamp change with no feature delta (SSE
        `event: layer_status`, api.md "## SSE")."""
        self._fan_out("layer_status", meta.model_dump(mode="json"))

    def publish_region_changed(self, region_id: str, bbox: Iterable[float]) -> None:
        """Publish an active-region switch (SSE `event: region_changed`,
        api.md "## SSE": `data` = `{region_id, bbox}`)."""
        self._fan_out("region_changed", {"region_id": region_id, "bbox": list(bbox)})
