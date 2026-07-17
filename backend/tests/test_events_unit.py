"""Unit tests for the in-process `EventBus` fan-out (backend/events.py).

These cover the parts of the SSE contract that the infinite-stream
acceptance test (test_api.py) can't exercise cheaply: multi-subscriber
fan-out, slow/stalled-client isolation (a full subscriber queue must never
block the publisher or starve healthy subscribers), the `region_changed` wire
shape, and `unsubscribe`. The scheduler write-path test only Mocks the bus, so
the real queue behavior is otherwise untested.

Per the durable repo rule, `backend.*` imports live inside each test body.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _layer_status_meta():
    from backend.models import Domain, LayerSnapshotMeta, LayerStatus

    ts = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    return LayerSnapshotMeta(
        layer=Domain.AIR,
        region_id="hormuz",
        status=LayerStatus.LIVE,
        timestamp_fetched=ts,
        timestamp_source=ts,
        cadence_s=600,
        stale_after_s=1200,
        feature_count=1,
    )


async def test_publish_fans_out_to_every_subscriber():
    from backend.events import EventBus

    bus = EventBus()
    sub_a = bus.subscribe()
    sub_b = bus.subscribe()

    meta = _layer_status_meta()
    bus.publish_layer_status(meta)

    for queue in (sub_a, sub_b):
        item = queue.get_nowait()
        assert item["event"] == "layer_status"
        assert item["data"] == meta.model_dump(mode="json")


async def test_layer_status_item_shape():
    from backend.events import EventBus

    bus = EventBus()
    queue = bus.subscribe()
    meta = _layer_status_meta()

    bus.publish_layer_status(meta)

    item = queue.get_nowait()
    assert set(item) == {"event", "data"}
    assert item["event"] == "layer_status"
    # `data` is already JSON-serializable (model_dump(mode="json")).
    assert isinstance(item["data"]["status"], str)


async def test_region_changed_wire_shape():
    from backend.events import EventBus

    bus = EventBus()
    queue = bus.subscribe()

    bus.publish_region_changed("gulf-of-oman", (56.5, 22.0, 62.0, 26.5))

    item = queue.get_nowait()
    assert item["event"] == "region_changed"
    assert item["data"] == {
        "region_id": "gulf-of-oman",
        "bbox": [56.5, 22.0, 62.0, 26.5],
    }
    # bbox is coerced to a plain list (JSON-friendly), not a tuple.
    assert isinstance(item["data"]["bbox"], list)


async def test_unsubscribe_stops_delivery_and_balances_count():
    from backend.events import EventBus

    bus = EventBus()
    assert bus.subscriber_count == 0
    queue = bus.subscribe()
    assert bus.subscriber_count == 1
    bus.unsubscribe(queue)
    assert bus.subscriber_count == 0

    bus.publish_layer_status(_layer_status_meta())

    import asyncio

    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()


async def test_stalled_subscriber_never_blocks_publisher_or_starves_others():
    """A slow subscriber that never drains its queue must not block the
    publisher (bounded queue, drop-oldest) nor starve a healthy subscriber
    that keeps up. Uses a tiny queue so the drop path is exercised in a few
    publishes (api.md "## SSE": a slow/closed client doesn't block others)."""
    from backend.events import EventBus

    bus = EventBus(queue_maxsize=2)
    fast = bus.subscribe()
    slow = bus.subscribe()  # never drained -> queue saturates and drops oldest

    metas = []
    for _ in range(4):
        meta = _layer_status_meta()
        metas.append(meta)
        # Must not raise / block despite `slow` being full after 2 publishes.
        bus.publish_layer_status(meta)
        # The fast subscriber keeps up, draining each event as it arrives.
        item = fast.get_nowait()
        assert item["data"] == meta.model_dump(mode="json")

    # Fast subscriber received all four and is now empty.
    import asyncio

    with pytest.raises(asyncio.QueueEmpty):
        fast.get_nowait()

    # Slow subscriber retained only the two most recent (oldest dropped), and
    # never blocked the publisher.
    assert slow.qsize() == 2
