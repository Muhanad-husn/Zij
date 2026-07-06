# Feature: sources-marine

`backend/sources/aisstream.py` (primary marine `StreamAdapter`, spec
`design/specs/aisstream.md`, §6.2/D2) and `backend/sources/aishub.py` (dormant secondary
`PollAdapter`, spec `design/specs/aishub.md`). The aisstream adapter holds one websocket,
maintains a latest-position table per MMSI, and serves point-in-time `snapshot()` on the
marine cadence — the table *is* the latest projection (FR3). AISHub proves the adapter
interface admits a polling marine source with **zero renderer change** (FR3 acceptance).

Consolidated from triage's 7-slice proposal to 3 (founder decision 2026-07-06, 80/20).

| Slice | Slug | Behaviour | Blocked-by | Skeleton |
|---|---|---|---|---|
| 01 | aisstream-core | connect + subscribe + read loop + message handling + `snapshot()` + `_prev_pos` | config/02 | ⭐ |
| 02 | aisstream-resilience | reconnect (backoff+jitter) + eviction sweep + `set_region` re-subscribe/clear | 01 | |
| 03 | aishub-dormant | dormant `PollAdapter`, 1 req/min floor, byte-compatible `LayerSnapshot(MARINE)` | — (v0 `base`) | |

Critical path: 01 → 02 (03 independent, can slip — unblocks nothing). All P0 except 03 (P0.10).
Tests: `backend/tests/test_aisstream.py` (mocked websocket replaying
`backend/tests/fixtures/aisstream_messages.jsonl`), `backend/tests/test_aishub.py` (respx).
**OQ1** (aisstream ToS / Gulf coverage / rate limits) gates only the *live* key — the build
runs entirely against the recorded fixture + mocked socket.
