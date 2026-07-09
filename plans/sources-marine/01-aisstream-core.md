# Slice 01: aisstream core — subscribe, message table, snapshot

- **Feature:** sources-marine
- **Slice slug:** aisstream-core
- **Issue:** #47
- **Branch:** feat/sources-marine/01-aisstream-core
- **Project directory:** `backend`
- **Status:** ▹ planned (sprint v1)
- **Walking skeleton?** yes ⭐

> **Zij roles (DEC-1):** **test-author** commits the outer acceptance test **red** before
> implementation; **implementer** drives inner cycles and may not edit the outer test or
> `design/`; **test-author** confirms green. Spec wrong mid-build ⇒ `spec-drift` issue.

## Goal — the minimum testable behaviour

`AisStreamAdapter(StreamAdapter)` holds the aisstream websocket and maintains a latest-position
table per MMSI. `start()` connects `cfg.ws_url` (the `websockets` lib) and immediately sends the
in-payload subscribe message — `APIKey` from `Secrets`, `BoundingBoxes` = `region.bbox` `[w,s,e,n]`
transformed to aisstream corner order `[[s,w],[n,e]]`, `FilterMessageTypes:["PositionReport",
"ShipStaticData"]` — then launches the read loop. A **PositionReport** builds/refreshes the MMSI
`_Entry` (lat/lon, `timestamp_source` from `MetaData.time_utc`, `attrs` sog_kn/cog_deg/heading_deg
[511 sentinel→None]/nav_status), copying the outgoing fix into `_prev_pos[MMSI]` (FR9 kinematics
input). A **ShipStaticData** enriches name/callsign/ship_type and refreshes `label` without
creating an entry or moving position. Sync `snapshot()` returns a `LayerSnapshot(domain=MARINE)`
point-in-time copy — computing `position_age_s`, de-emphasizing `age > deemphasize_after_s` (1800 s)
to `FeatureStatus.STALE`, excluding `age > drop_after_s` (7200 s) — with no I/O and never raising.

## INVEST check

- **Independent:** consumes only `models` + `sources/base` + config; the socket is mocked.
- **Valuable:** first marine data end-to-end; the table-is-the-projection primitive the scheduler samples.
- **Small:** one adapter, the `_table`/`_prev_pos` dicts, two message handlers, `snapshot()`.
- **Testable:** a recorded `backend/tests/fixtures/aisstream_messages.jsonl` replayed through a mocked ws — no live feed (OQ1 gates only the live key).

## Acceptance criterion (outer loop — the failing test)

```gherkin
Given the recorded aisstream messages fed through a mocked websocket
When  the read loop processes a PositionReport then a ShipStaticData for the same MMSI
Then  snapshot() returns one MARINE feature carrying position, enriched name, SOG and COG
And   _prev_pos holds that MMSI's prior fix (lat, lon, timestamp_source) for FR9
And   a vessel silent > 30 min renders FeatureStatus.STALE and one silent > 2 h is excluded
And   snapshot() performs no I/O and never raises
```

- **Boundary:** `AisStreamAdapter` public surface (`start`/`snapshot`/`connected`) over a mocked socket.
- **test type:** pytest-asyncio integration; **file:** `backend/tests/test_aisstream.py`.

## Inner loop — initial unit test list

- [ ] bbox `[w,s,e,n]` → aisstream `[[s,w],[n,e]]` corner transform in the subscribe payload.
- [ ] PositionReport → `_Entry` mapping; `TrueHeading` 511 sentinel maps `heading_deg=None`.
- [ ] ShipStaticData enriches name/callsign/ship_type, refreshes `label`, does **not** move `last_heard`/position.
- [ ] Overwriting an entry copies the outgoing `(lat,lon,timestamp_source)` into `_prev_pos[MMSI]`.
- [ ] Aging: `age > deemphasize_after_s` → STALE; `age > drop_after_s` → excluded from snapshot.
- [ ] `snapshot()` returns fresh Feature objects (point-in-time copy), does no I/O, never raises.

## Out of scope (deferred)

- Reconnect / backoff / eviction sweep / `set_region` (slice 02).
- Integrity flags (integrity feature); scheduler sampling + status (scheduler feature).
- AISHub (slice 03).

## Definition of done

- [ ] Outer test authored **RED before implementation** (DEC-1), seen red, now GREEN.
- [ ] Inner units covered; `uv run pytest`, `uv run ruff` green; refactor on green.
- [ ] Evidence: pytest transcript over the recorded fixture. CI green; PR via `safe-pr`.

## Status / progress log

- 2026-07-06 planned (sprint v1). Blocked-by: config/02 (marine/aisstream config sections).
  Needs the recorded `aisstream_messages.jsonl` fixture (capture-script companion to v0 fixtures).
- 2026-07-09 built. Outer test red `782a3df` (strict-xfail) → green `4a7a1f7` → review fixes
  `b4e207f` → evidence `9e7d9e3`. 151 tests green, ruff clean. Two-stage review PASS (stage-1)
  / DONE_WITH_CONCERNS (stage-2, both actionable findings fixed). Follow-ups filed: #73
  (spec-drift, `connected` timing) + #74 (`stop()` await, → slice 02). PR: #77 (Closes #47).
  Status: DONE_WITH_CONCERNS (concerns resolved pre-PR; deferred items filed). Awaiting merge approval.
