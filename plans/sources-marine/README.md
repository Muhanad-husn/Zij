# Feature: sources-marine

`backend/sources/aisstream.py` (primary marine `StreamAdapter`, spec
`design/specs/aisstream.md`, §6.2/D2). The aisstream adapter holds one websocket,
maintains a latest-position table per MMSI, and serves point-in-time `snapshot()` on the
marine cadence — the table *is* the latest projection (FR3).

Consolidated from triage's 7-slice proposal to 3 (founder decision 2026-07-06, 80/20);
slice 03 (AISHub dormant adapter) was later cancelled — AISHub gates access behind an owned
receiver feed, so aisstream.io is the marine source.

| Slice | Slug | Behaviour | Blocked-by | Skeleton |
|---|---|---|---|---|
| 01 | aisstream-core | connect + subscribe + read loop + message handling + `snapshot()` + `_prev_pos` | config/02 | ⭐ |
| 02 | aisstream-resilience | reconnect (backoff+jitter) + eviction sweep + `set_region` re-subscribe/clear | 01 | |

Critical path: 01 → 02. Both P0.
Tests: `backend/tests/test_aisstream.py` (mocked websocket replaying
`backend/tests/fixtures/aisstream_messages.jsonl`).
**OQ1** (aisstream ToS / Gulf coverage / rate limits) gates only the *live* key — the build
runs entirely against the recorded fixture + mocked socket.
