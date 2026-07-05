# Contract — Source Adapter Interface

Design for `backend/sources/base.py`. Implements the adapter side of PRD §10, FR2/FR3/FR4/FR6/FR10, and the source-swap mitigation (§12). Returns [`LayerSnapshot`](feature-schema.md#layersnapshot--metadata). The scheduler owns lifecycle and status; see [ARCHITECTURE §5](../docs/ARCHITECTURE.md#5-failure-isolation-fr10-and-the-layer-status-state-machine).

## Two adapter shapes

The two source access patterns from the PRD map to two base classes:

- **`PollAdapter`** — request/response. `fetch(region) → LayerSnapshot`. Used by **OpenSky** (§6.1), **Overpass** (§6.3), **AISHub** (§6.2, dormant). The scheduler calls `fetch` on cadence.
- **`StreamAdapter`** — long-running task holding a websocket and internal state; the scheduler samples it on cadence via a synchronous `snapshot()`. Used by **aisstream** (§6.2): the rolling MMSI table *is* the latest projection.

Both return the identical `LayerSnapshot`, so the renderer is shape-agnostic — this is what makes FR3's "AISHub swaps in without renderer changes" true **by construction** ([§ renderer independence](#renderer-independence-fr3)).

## Region type

```python
from pydantic import BaseModel, Field

class Region(BaseModel):
    id: str                 # "hormuz" | "custom:<hash>"
    label: str
    # bbox in [west, south, east, north] degrees (WGS84). See config.md.
    bbox: tuple[float, float, float, float]
```

## Base classes

```python
from abc import ABC, abstractmethod
from backend.models import Domain, LayerSnapshot


class SourceAdapter(ABC):
    """Common metadata + lifecycle. Adapters NEVER touch the UI, the registry,
    or status. They return a LayerSnapshot or raise a typed AdapterError."""
    domain: Domain          # class attribute
    source: str             # class attribute: "opensky" | "aisstream" | ...

    async def start(self) -> None:
        """Optional warmup. PollAdapters may prefetch an OAuth token / open an
        httpx.AsyncClient. Default: no-op. Must be idempotent."""

    async def stop(self) -> None:
        """Release resources (close httpx client / websocket). Must be safe to
        call during cancellation. Default: no-op."""


class PollAdapter(SourceAdapter):
    @abstractmethod
    async def fetch(self, region: Region) -> LayerSnapshot:
        """Fetch current state for region. MUST be cancellable (awaits only).
        Sets feature-level status/timestamps; leaves LayerSnapshot.meta.status
        as LIVE — the scheduler overwrites meta.status authoritatively.
        Raises: RateLimitedError | AuthError | UpstreamError | ParseError."""


class StreamAdapter(SourceAdapter):
    @abstractmethod
    async def start(self) -> None:
        """Open the websocket and launch the internal read loop as a task that
        maintains the latest-position table. Returns once subscribed."""

    @abstractmethod
    async def stop(self) -> None:
        """Close the websocket, cancel the read loop."""

    @abstractmethod
    async def set_region(self, region: Region) -> None:
        """Re-subscribe the upstream feed to region.bbox and clear the table
        for the new region (aisstream must re-send its bbox subscription).
        Called by the scheduler on region switch."""

    @abstractmethod
    def snapshot(self) -> LayerSnapshot:
        """SYNCHRONOUS. Read the in-memory table and return the current
        projection. Applies the 30-min de-emphasis / 2-hr drop windows (FR3)
        against 'now'. Must not do I/O. Never raises AdapterError; connection
        health is reported via an internal flag the scheduler reads (below)."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """True while the websocket is up. When False the scheduler renders the
        marine layer 'reconnecting' (FR3) while snapshot() still serves the last
        table."""
```

## Async lifecycle & region propagation

Managed by `scheduler.py` inside an `asyncio.TaskGroup` (single loop, [ADR-8](../docs/DECISIONS.md#adr-8--concurrency-pure-asyncio)):

1. **Startup:** scheduler calls `start()` on every enabled adapter. `StreamAdapter.start()` opens the aisstream socket and subscribes the active region's bbox.
2. **Poll tick:** on each layer's cadence, scheduler `await`s `fetch(region)` inside a per-layer `try/except` (failure isolation, FR10). Manual refresh coalesces onto the in-flight awaitable (FR6 — never double-spends OpenSky credits).
3. **Stream sample:** on the marine display cadence, scheduler calls `snapshot()` (sync, cheap), runs integrity, updates registry, emits SSE.
4. **Region switch:** scheduler cancels in-flight `fetch` tasks; for the stream adapter calls `set_region(new)` → aisstream re-subscribes the new bbox and clears its table ([ARCHITECTURE §4.2](../docs/ARCHITECTURE.md#42-region-switch)).
5. **Shutdown:** scheduler calls `stop()` on all adapters; cancellation propagates into any in-flight `fetch` (adapters close clients in `finally`).

## Error taxonomy

```python
class AdapterError(Exception):
    """Base. Carries an optional human message surfaced in LayerStatus.detail."""

class RateLimitedError(AdapterError):
    def __init__(self, retry_after: float | None = None, message: str = ""):
        self.retry_after = retry_after   # seconds, from Retry-After header if present
        super().__init__(message)

class AuthError(AdapterError):
    """401/403, invalid/expired credentials, OAuth token acquisition failure."""

class UpstreamError(AdapterError):
    """5xx, connection error, timeout, Overpass 504 — transient upstream fault."""

class ParseError(AdapterError):
    """Response received but unparseable / schema-invalid (Pydantic validation)."""
```

### Scheduler handling (who retries vs. surfaces)

| Error | Scheduler action | Resulting `LayerStatus` |
|---|---|---|
| `RateLimitedError(retry_after)` | Honor `retry_after` (or config backoff), then retry. **Retries.** | `rate-limited` (→ `cached-fallback` if warm cache, FR8) |
| `UpstreamError` | Exponential backoff retry (config caps attempts). **Retries.** | `error`, or `cached-fallback` if warm cache (FR10) |
| `AuthError` | **Surfaces, no auto-retry** — needs credential fix (NFR5). Log + badge. | `error` |
| `ParseError` | **Surfaces, no retry** — retrying won't help; log for the operator. Keep last good snapshot. | `error` (or keep prior `live`/`cached-fallback`) |

Backoff/attempt caps and stale multiplier are config, not hardcoded ([config.md](config.md)).

## Status ownership

Adapters **return or raise; they never set layer status**. The scheduler maps outcomes to `LayerStatus` per the state machine in [ARCHITECTURE §5](../docs/ARCHITECTURE.md#5-failure-isolation-fr10-and-the-layer-status-state-machine) and the table above. Rationale (FR10, PRD §10): status is a system-level concern (it depends on cache presence, timing, and the 2× stale rule the adapter can't see), and centralizing it is what keeps one adapter's failure from leaking into another's badge. `LayerSnapshotMeta.status` returned by an adapter is advisory (`live`) and always overwritten.

## Renderer independence (FR3)

The contract guarantees the FR3 acceptance criterion "the adapter interface admits an AISHub polling implementation without changes to the renderer":

- AISHub is a `PollAdapter` (§6.2 1-req/min is compatible with the poll cadence); aisstream is a `StreamAdapter`. **Both return `LayerSnapshot` with `domain = MARINE`.**
- The scheduler's marine-sampling code is identical for either (poll `fetch` vs. sample `snapshot()` differ only in the scheduler's source-shape branch, chosen at wiring time from [config.md](config.md)).
- The frontend renders `LayerSnapshot` and never learns which marine source produced it (shell boundary, [ARCHITECTURE §6](../docs/ARCHITECTURE.md#6-the-shell-boundary-d1-no-rewrite-promise)).

Swapping marine sources is therefore a one-file backend change with zero renderer impact — the §12 "swapping a source is a bounded task" mitigation, enforced by types.
