"""Snapshot registry (spec: design/specs/scheduler.md "Snapshot registry").

The single source of truth for the current per-layer state: an in-memory
`dict[Domain, LayerSnapshot]` holding full `Feature`s **with** `raw_payload`
(feature-schema.md). No SSE, no persistence -- both are separate collaborators
(`events.py`, `store.py`) the scheduler writes to after this registry, per the
frozen write-path order. Kept minimal and honest for this slice: a thin
`dict` subclass adds nothing beyond genuine `dict[Domain, LayerSnapshot]`
semantics, which is exactly what the write path (`registry[domain] = snap`)
and the air-`prev` derivation (`registry[Domain.AIR].features`, `.get`/
`KeyError` on a missing domain) need.
"""

from __future__ import annotations

from backend.models import Domain, LayerSnapshot


class Registry(dict[Domain, LayerSnapshot]):
    """`dict[Domain, LayerSnapshot]` (scheduler.md "Snapshot registry")."""
