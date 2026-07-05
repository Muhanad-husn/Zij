# Spec — `sources/aishub.py` (AISHub PollAdapter, dormant)

**Purpose.** Secondary marine `PollAdapter` (§6.2, D2), **dormant**: activated only if an owned AIS receiver is commissioned (OQ2). It exists to prove the adapter interface admits a polling marine source with **zero renderer change** (FR3 acceptance criterion). Not wired into config by default.

## Public interface
```python
class AisHubAdapter(PollAdapter):
    domain = Domain.MARINE          # SAME domain as aisstream
    source = "aishub"
    async def start(self) -> None; async def stop(self) -> None
    async def fetch(self, region: Region) -> LayerSnapshot
```
Returns `LayerSnapshot(domain=MARINE)` — byte-for-byte the same contract the scheduler's marine path consumes; the scheduler picks poll-`fetch` vs stream-`snapshot()` at wiring time from config ([adapter-interface.md §renderer-independence](../contracts/adapter-interface.md#renderer-independence-fr3)).

## Internal design (kept minimal)
- **Rate floor: 1 request/minute** (§6.2). The adapter enforces its own floor: reject/serve-last if called <60 s since last fetch, independent of any scheduler cadence. The marine `cadence_s` (60 s) is already at this floor, so no extra throttle is normally hit.
- `GET https://data.aishub.net/ws.php?username=<AISHUB_USERNAME>&format=1&output=json&compress=0&latmin=&latmax=&lonmin=&lonmax=` with bbox from `region.bbox`. One shared httpx `AsyncClient`, 30 s timeout.
- **Feature mapping** — identical target schema to aisstream: `source_id`=MMSI, `label`=NAME, `lat/lon`, `attrs.sog_kn`/`cog_deg`/`heading_deg`/`nav_status`, `timestamp_source` from the record's report time, `position_age_s = now - timestamp_source`, `geometry_type=POINT`. `raw_payload`=record dict.
- Same FR3 aging semantics are the **snapshot consumer's** job; a poll adapter simply returns the current set. (De-emphasis/drop windows apply in the renderer/scheduler using `position_age_s` + `[layers.marine]` thresholds, so behavior matches the stream path.)
- No websocket, no MMSI table, no reconnect — request/response only.

## Failure modes
Standard taxonomy: `429`→`RateLimitedError`, `5xx`/timeout→`UpstreamError`, auth/`username` rejected→`AuthError`, bad JSON→`ParseError`.

## Configuration consumed
Secret `AISHUB_USERNAME`; `[layers.marine]` thresholds. **Not** listed as the active marine source in bundled `config.toml`; enabling is an operator wiring change (swap the marine adapter class) — the §12 "bounded task" swap.

## Acceptance criteria
- [ ] **FR3** — the adapter implements `PollAdapter` and returns `LayerSnapshot(domain=MARINE)` consumable by the renderer with no renderer/frontend change vs aisstream.
- [ ] **§6.2** — self-enforced 1 req/min floor.
- [ ] Dormant by default: absent from bundled config; requires only `AISHUB_USERNAME` + a one-line wiring swap to activate.
