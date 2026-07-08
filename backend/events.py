"""In-process event bus (spec: design/specs/scheduler.md "Write path" step 5).

`EventBus.publish_snapshot` is the seam the scheduler calls after the
registry is set; the actual SSE endpoint (`snapshot`/`layer_status`/
`region_changed` streaming to clients, api.md#sse) is out of scope here and
lands in api-core/01. `raw_payload` never rides a published snapshot --
`Feature.raw_payload` is declared `exclude=True` (models.py), so any
`model_dump()`/`model_dump_json()` of a published `LayerSnapshot` already
drops it; this module does no extra stripping.
"""

from __future__ import annotations

from backend.models import LayerSnapshot


class EventBus:
    """Minimal in-process publish seam. Synchronous by design (scheduler.md
    "Write path" step 5 reads only `events.publish_snapshot(snap)`, no
    `await`, unlike step 6's `await store.put_fallback(snap)`)."""

    def publish_snapshot(self, snap: LayerSnapshot) -> None:
        """Publish a full snapshot (SSE `snapshot` event, once wired)."""
