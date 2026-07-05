"""Source adapter interface (contract: design/contracts/adapter-interface.md).

Transcribed verbatim from the frozen contract. Implements the adapter side of
PRD §10, FR2/FR3/FR4/FR6/FR10, and the source-swap mitigation (§12). Adapters
never touch the UI, the registry, or status: they return a `LayerSnapshot` or
raise a typed `AdapterError`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from backend.models import Domain, LayerSnapshot


class Region(BaseModel):
    id: str  # "hormuz" | "custom:<hash>"
    label: str
    # bbox in [west, south, east, north] degrees (WGS84). See config.md.
    bbox: tuple[float, float, float, float]


class SourceAdapter(ABC):
    """Common metadata + lifecycle. Adapters NEVER touch the UI, the registry,
    or status. They return a LayerSnapshot or raise a typed AdapterError."""

    domain: Domain  # class attribute
    source: str  # class attribute: "opensky" | "aisstream" | ...

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
        as LIVE -- the scheduler overwrites meta.status authoritatively.
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
        """True while the websocket is up. When False the scheduler renders
        the marine layer 'reconnecting' (FR3) while snapshot() still serves
        the last table."""


class AdapterError(Exception):
    """Base. Carries an optional human message surfaced in LayerStatus.detail."""


class RateLimitedError(AdapterError):
    def __init__(self, retry_after: float | None = None, message: str = ""):
        self.retry_after = retry_after  # seconds, from Retry-After header if present
        super().__init__(message)


class AuthError(AdapterError):
    """401/403, invalid/expired credentials, OAuth token acquisition failure."""


class UpstreamError(AdapterError):
    """5xx, connection error, timeout, Overpass 504 -- transient upstream fault."""


class ParseError(AdapterError):
    """Response received but unparseable / schema-invalid (Pydantic validation)."""
