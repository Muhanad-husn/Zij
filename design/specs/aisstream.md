# Spec — `sources/aisstream.py` (aisstream StreamAdapter)

**Purpose.** Marine primary `StreamAdapter` (§6.2, D2): holds one aisstream.io websocket, maintains a latest-position table per MMSI, and serves point-in-time `snapshot()` on the marine display cadence. The table *is* the latest projection ([adapter-interface.md](../contracts/adapter-interface.md)).

Contracts honored: `snapshot()` is synchronous, does no I/O, never raises; connection health is exposed via `connected`; the scheduler owns `LayerStatus`.

## Public interface

```python
class AisStreamAdapter(StreamAdapter):
    domain = Domain.MARINE
    source = "aisstream"

    def __init__(self, cfg: AisStreamCfg, secrets: Secrets): ...

    async def start(self) -> None                 # connect + subscribe + launch read loop
    async def stop(self) -> None                  # close ws, cancel read loop
    async def set_region(self, region: Region) -> None  # re-subscribe, clear table
    def snapshot(self) -> LayerSnapshot           # sync, point-in-time copy
    @property
    def connected(self) -> bool
```

`AisStreamCfg` = `[aisstream]` + `[layers.marine]` (config.md).

## Internal design

### State
```python
_table: dict[str, _Entry]           # MMSI -> latest entry
_prev_pos: dict[str, _PrevPos]      # MMSI -> previous (lat, lon, ts) for FR9 kinematics
_region: Region | None
_ws / _read_task: asyncio.Task
_connected: bool
```
`_Entry` = `{feature: Feature, last_heard: datetime, name: str|None, callsign: str|None}`. All timestamps UTC. Single event loop → no lock needed (dict mutation and `snapshot()` copy both run as loop-atomic sync sections; `snapshot()` never awaits, so it cannot interleave with the read loop, [ADR-8](../docs/DECISIONS.md#adr-8--concurrency-pure-asyncio)).

### Websocket lifecycle
- Connect `cfg.ws_url` (`wss://stream.aisstream.io/v0/stream`) via the `websockets` library ([ADR-9](../docs/DECISIONS.md#adr-9--http--websocket-clients)).
- **Subscribe message** sent immediately on connect (auth is in-payload, not a header):
  ```json
  {"APIKey":"<AISSTREAM_API_KEY>",
   "BoundingBoxes":[[[south,west],[north,east]]],
   "FilterMessageTypes":["PositionReport","ShipStaticData"]}
  ```
  Note aisstream corner order is `[lat,lon]` = `[[s,w],[n,e]]` — transform from `region.bbox=[w,s,e,n]`. `PositionReport` is the FR3 minimum; `ShipStaticData` is subscribed to enrich `name`/`callsign` (FR3 popup).
- **Read loop** (`_read_task`): `async for raw in ws:` → parse JSON → dispatch by `MessageType`. Sets `_connected=True` **once the subscribe payload is sent** — aisstream.io has no formal subscribe-ack frame, and a correct bbox over a quiet region can legitimately produce no messages, so waiting for a first message would leave `connected` permanently false and render a false `reconnecting`.

### Message handling
- **PositionReport** → build/refresh `_Entry` for `MetaData.MMSI`:
  - `lat/lon` from `Message.PositionReport.Latitude/Longitude`; `timestamp_source` from `MetaData.time_utc` (UTC parse); `last_heard = now`.
  - `attrs`: `sog_kn` (`Sog`), `cog_deg` (`Cog`), `heading_deg` (`TrueHeading`, drop sentinel 511→None), `nav_status` (`NavigationalStatus`). Source-native units, keyed with unit suffix (feature-schema.md Units).
  - Before overwriting, copy the outgoing entry's `(lat,lon,timestamp_source)` into `_prev_pos[MMSI]` (FR9 input for integrity.py).
  - Carry forward enriched `name`/`callsign` from any prior static message; `label = name or None`.
  - `raw_payload` = the full message dict (in-memory only).
- **ShipStaticData** → update `_Entry.name` (`ShipName`/`Name`), `_Entry.callsign` (`CallSign`), `attrs.ship_type` (`Type`), and refresh the feature's `label`. Does **not** create an entry on its own or move `last_heard`/position (static ≠ a position fix).
- Parse errors on a single message are logged and skipped (one bad frame must not kill the stream); they never raise out of the read loop.

### `snapshot()` (sync, cadence-sampled)
1. `now = datetime.now(UTC)`.
2. Build `features` from `_table`, computing `position_age_s = now - timestamp_source`.
3. **Aging (FR3):**
   - `age > cfg.deemphasize_after_s` (1800 s / 30 min) → `FeatureStatus.STALE` (de-emphasis input). Uniform rule with the poll adapters (opensky.md stamps the same way against `[layers.air].deemphasize_after_s`); the renderer additionally ages features client-side and de-emphasizes if wire `status == STALE` **OR** client-computed age exceeds the threshold (frontend.md §9).
   - else `FeatureStatus.LIVE`.
   - `age > cfg.drop_after_s` (7200 s / 2 h) → **excluded** from the snapshot (eviction proper happens in the sweep below; snapshot also filters so a between-sweeps sample never shows a >2 h vessel).
4. `meta.timestamp_source` = newest entry `timestamp_source`; `meta.status = LIVE` (advisory; scheduler overwrites — sets `reconnecting` when `connected` is False).
5. Returns a fresh `LayerSnapshot`; features are new objects (point-in-time copy). Called on the marine 60 s cadence and on refresh-now (FR6) — identical code path.

### Eviction sweep
A lightweight periodic coroutine inside the adapter (every `cfg.cadence_s`, i.e. 60 s, piggybacked on/parallel to the read loop) removes `_table`/`_prev_pos` entries with `age > drop_after_s`. Keeps memory bounded; `snapshot()` also filters defensively so sweep timing is not load-bearing for correctness.

### Reconnect (FR3)
- **Abnormal close / read error only** (`ConnectionClosedError` propagating from the read loop, or any other read exception): set `_connected=False`, then reconnect with **exponential backoff + full jitter**: `delay = random.uniform(0, min(cfg.reconnect_max_s, cfg.reconnect_base_s * 2**attempt))` (base 2 s, max 60 s). Reset `attempt=0` on a successful subscribe.
- **Graceful close does NOT reconnect.** A clean close (`ConnectionClosedOK`, surfacing as a normal end of the `async for`) leaves `_connected=False` persistently, with an operator-visible `detail` — no reconnect loop (see Failure modes). Why: a bad API key surfaces as a graceful close, and unconditionally reconnecting would hammer aisstream with a known-bad key (a reconnect storm); persistent disconnect instead keeps the auth failure operator-visible.
- A close-code-aware refinement — reconnect on a graceful close *only* after a session that had actually streamed data (distinguishing a bad key from a legitimate idle close) — was considered and deliberately deferred: it would require revising slice-01's locked outer acceptance test, which drains a finite fixture and awaits the read task to completion.
- **Table retention across reconnects: keep.** Data ages naturally via `last_heard`; dropping it would blank the map on every transient drop. `_connected=False` makes the scheduler render `reconnecting` while `snapshot()` still serves the aging table.
- `_prev_pos` also retained (kinematics continuity survives a blip).

### `set_region` (region switch)
**Tear down and re-subscribe** (not dynamic add/remove): send a fresh subscribe message with the new bbox on the existing socket if open, else it applies on next connect. **Clear `_table` and `_prev_pos`** — the new region is a different vessel population (ARCHITECTURE §4.2). Chosen over dynamic bbox editing because aisstream's subscription model resends the full bbox set anyway and clearing is the correct UX (old-region ghosts must not linger).

## Failure modes
- Abnormal websocket drop / network error (`ConnectionClosedError` / read exception) → reconnect loop (Reconnect above); layer shows `reconnecting` then `cached-fallback`/`live`. Never raises to the scheduler (stream health via `connected`).
- Auth failure (bad API key → server closes the socket, surfacing as a **graceful close** `ConnectionClosedOK`): the read loop ends and leaves persistent `_connected=False` with a `detail` string; **no reconnect** (Reconnect above), so a known-bad key does not trigger a reconnect storm. Operator-visible. No credit concept here.
- Malformed single message → skip + log.

## Configuration consumed
`[aisstream]` (`ws_url`, `reconnect_base_s`, `reconnect_max_s`); `[layers.marine]` (`cadence_s`, `deemphasize_after_s`, `drop_after_s`, `custom_bbox_cap_sq_deg`); secret `AISSTREAM_API_KEY` (config.md).

## Acceptance criteria
- [ ] **FR3** — an abnormal websocket drop / read error triggers reconnect with exponential backoff + jitter; `connected` goes False so the scheduler shows `reconnecting`; `snapshot()` keeps serving. A graceful close (`ConnectionClosedOK`, e.g. a bad API key) goes persistently disconnected with an operator-visible `detail` and does **not** reconnect.
- [ ] **FR3** — a vessel silent >30 min renders de-emphasized (`FeatureStatus.STALE`); silent >2 h is dropped from `snapshot()` and evicted from the table.
- [ ] **FR3** — `set_region` re-subscribes the new bbox and clears the table; no old-region vessels appear after switch.
- [ ] **FR6** — `snapshot()` on the 60 s cadence and on refresh-now returns a point-in-time copy without I/O or raising.
- [ ] **FR9** — `_prev_pos[MMSI]` holds the previous fix so integrity.py can compute implied speed; guarded against same-timestamp (integrity.py's concern).
- [ ] **FR3 (renderer independence)** — returns `LayerSnapshot(domain=MARINE)` identical in shape to a poll adapter's.
- [ ] **NFR5** — API key only in the subscribe payload, read from `Secrets`; never on the wire to the frontend.
