# Contract — HTTP + SSE API

The full backend surface (`backend/main.py`). Precise enough that frontend and backend build independently against it. Models referenced here are defined in [feature-schema.md](feature-schema.md). Serving model (dev proxy / prod static) in [ADR-7](../docs/DECISIONS.md#adr-7--dev-vs-prod-frontend-serving); SSE reconnection in [ADR-12](../docs/DECISIONS.md#adr-12--sse-reconnection).

Base path: **`/api`**. All bodies JSON, UTF-8. All timestamps ISO-8601 UTC `Z` (NFR6). Single-origin in prod → no CORS; localhost/single-user → no auth in v1 (credentials are for *upstream* sources, never exposed here — NFR5).

## Error envelope

Every non-2xx response uses:

```json
{ "error": {
  "code": "rate_limited",
  "message": "OpenSky returned 429; retrying after 42s.",
  "retry_after_s": 42,
  "details": {}
}}
```

`code` ∈ `{bad_request, not_found, validation_error, rate_limited, upstream_error, auth_error, conflict, internal}`. HTTP status matches (400/404/422/429/502/401/409/500). `retry_after_s` present only for `rate_limited` (also mirrored in the `Retry-After` header).

Note: a **layer** being rate-limited is normal operating state conveyed via SSE `layer_status` (not an HTTP error). The `429` envelope above is only for a *request* the server itself refuses.

---

## REST

### GET /api/health
Liveness. `200 → {"status":"ok","version":"0.1.0","uptime_s":1234.5}`.

### GET /api/config
Effective non-secret config (regions, cadences, caps, mirrors — [config.md](config.md)). Never returns secrets (NFR5). The `layers` object mirrors config.md's per-layer tables as JSON (the frontend reads de-emphasis/drop/cadence thresholds from here — [frontend.md §9](../specs/frontend.md#9-state-handling)).
```json
{ "regions": [RegionInfo],
  "layers": {
    "air":    {"enabled": true, "cadence_s": 600, "cadence_floor_s": 60,
               "deemphasize_after_s": 60, "stale_multiplier": 2, "custom_bbox_cap_sq_deg": 100},
    "marine": {"enabled": true, "cadence_s": 60, "cadence_floor_s": 60,
               "deemphasize_after_s": 1800, "drop_after_s": 7200, "stale_multiplier": 2,
               "custom_bbox_cap_sq_deg": 40},
    "land":   {"enabled": true, "cadence_s": 86400, "cadence_floor_s": 3600,
               "stale_multiplier": 2, "simplify_tolerance_deg": 0.0005,
               "max_rendered_features": 5000, "custom_bbox_cap_sq_deg": 40}
  }
}
```

### GET /api/regions
List predefined + saved presets (FR1, FR11).
```json
{ "regions": [
  {"id":"hormuz","label":"Strait of Hormuz","bbox":[55.0,25.0,57.5,27.5],
   "aviation_credit_cost":1,"kind":"predefined"},
  {"id":"custom:ab12","label":"My Box","bbox":[52.0,26.0,55.0,28.0],
   "aviation_credit_cost":1,"kind":"preset"}
]}
```
Every `RegionInfo` carries `kind ∈ {predefined, preset, custom}`. `predefined` is a
config-shipped region; `preset` is a saved custom bbox (`config_presets`). `custom`
denotes an activated bounding box that was **not** saved as a preset — it exists only
as the active region for this session. `GET /api/regions` lists only `predefined` and
`preset`; a `custom` region never appears here, and is returned solely by
`POST /api/regions/activate` and `GET /api/regions/active`.

### POST /api/regions/estimate
Validate a custom bbox and price it **before** activation (FR1). No side effects.

Request: `{ "bbox": [west, south, east, north] }`

Each `layer_caps` entry is `{ok, cap_sq_deg, cost_credits?, message?}`; `message` is present only when `ok:false` and names the exceeded cap (FR1 acceptance).

`200` (valid):
```json
{ "valid": true,
  "bbox": [52.0, 26.0, 56.0, 29.0],
  "area_sq_deg": 12.0,
  "aviation_credit_cost": 1,
  "layer_caps": {
    "air":  {"ok": true,  "cap_sq_deg": 100, "cost_credits": 1},
    "land": {"ok": true,  "cap_sq_deg": 40},
    "marine":{"ok": true, "cap_sq_deg": 40}
  }
}
```
If a layer cap is exceeded, `valid:false` and that layer's `ok:false` carries `message` — returned as `422 validation_error` with the same body under `details`:
```json
{ "valid": false,
  "bbox": [40.0, 20.0, 55.0, 32.0],
  "area_sq_deg": 180.0,
  "aviation_credit_cost": 3,
  "layer_caps": {
    "air":  {"ok": true,  "cap_sq_deg": 100, "cost_credits": 3},
    "land": {"ok": false, "cap_sq_deg": 40, "message": "Land bbox 180.0 sq° exceeds the 40 sq° cap."},
    "marine":{"ok": false, "cap_sq_deg": 40, "message": "Marine bbox 180.0 sq° exceeds the 40 sq° cap."}
  }
}
```

### POST /api/regions/activate
Activate a predefined region or a validated custom bbox. Triggers fetches only for **enabled** layers (FR1, FR5).

Request (one of):
```json
{ "region_id": "hormuz" }
{ "bbox": [52.0, 26.0, 56.0, 29.0], "label": "My Box", "save_as_preset": false }
```
Custom bbox is re-validated server-side (caps + credit estimate); on cap violation → `422` with the estimate body. `200 → { "active_region": RegionInfo }`. Side effects per [ARCHITECTURE §4.2](../docs/ARCHITECTURE.md#42-region-switch); layer updates arrive over SSE, not in this response.

### GET /api/regions/active
`200 → { "active_region": RegionInfo | null }`.

### GET /api/layers/{domain}/snapshot
`domain ∈ {air, marine, land}`. Current [`LayerSnapshot`](feature-schema.md#layersnapshot--metadata) from the registry (pull fallback for SSE). `raw_payload` excluded. `404 not_found` if no active region. Used for initial load and reconnect-independent fetches.

### POST /api/layers/{domain}/toggle
Enable/disable a layer (FR5). Disabled layers consume no upstream budget.
Request: `{ "enabled": false }` → `200 → { "layer":"air", "enabled":false }`. Disabling stops that adapter's scheduling; enabling starts it and triggers an immediate fetch.

### POST /api/layers/{domain}/refresh
Force-refresh one layer (FR6). Poll layer → immediate coalesced fetch; marine → immediate `snapshot()`. `202 → { "layer":"air", "queued":true }`. Result via SSE.

### POST /api/refresh
Refresh **all enabled** layers (FR6). `202 → { "queued": ["air","marine"] }`.

### GET /api/layers/{domain}/caveats
FR9 caveat text (persistent, non-dismissible panel). Static per domain + any active integrity-flag counts from the current snapshot.
```json
{ "domain":"marine",
  "caveats":[
    "Terrestrial AIS coverage in the Persian Gulf is receiver-dependent and uneven.",
    "Dark-fleet vessels routinely disable AIS and will not appear.",
    "GPS jamming produces on-land and circular ghost tracks."],
  "active_flags": {"spoof_suspect_on_land": 3, "implausible_kinematics": 1}
}
```

### GET /api/features/{domain}/{source_id}/raw
FR11 popup raw-payload inspection. Returns the untouched upstream record from the live registry ([feature-schema.md raw_payload](feature-schema.md#raw_payload-handling)). Designed now even though P1.
`200 → { "domain":"air","source_id":"896451","source":"opensky","raw_payload": { ... } }`.
`404 not_found` if the feature has rotated out of the current snapshot.

### Presets (FR11, P1 — designed now)
- `GET /api/presets` → `{ "presets":[{id,name,bbox,created_at}] }`
- `POST /api/presets` `{ "name":"...", "bbox":[...] }` → `201`; `409 conflict` on duplicate name.
- `DELETE /api/presets/{id}` → `204`.

Persisted to `config_presets` ([storage.md](storage.md)).

---

## SSE

### GET /api/events
Single `text/event-stream` (sse-starlette, [ADR-2](../docs/DECISIONS.md#adr-2--sse-via-sse-starlette)). The frontend opens exactly one `EventSource`. **Full-state-on-connect** ([ADR-12](../docs/DECISIONS.md#adr-12--sse-reconnection)): on every (re)connect the server first emits a `snapshot` for each enabled layer from the registry, then streams incremental events. No replay buffer; `Last-Event-ID` accepted but advisory.

Each event has `event:` and `data:` (JSON) and a monotonic `id:`.

**`event: snapshot`** — full layer replacement. `data` = [`LayerSnapshot`](feature-schema.md#layersnapshot--metadata) (raw_payload excluded).
```
event: snapshot
id: 1287
data: {"meta":{"layer":"air","region_id":"hormuz","status":"live",...},"features":[...]}
```

**`event: layer_status`** — status/timestamp change with no feature delta (e.g. `live→rate-limited`, stale flip). `data` = [`LayerSnapshotMeta`](feature-schema.md#layersnapshot--metadata) only (cheap).
```
event: layer_status
id: 1290
data: {"layer":"marine","region_id":"hormuz","status":"reconnecting",
       "timestamp_fetched":"2026-07-05T09:12:00Z","timestamp_source":"2026-07-05T09:11:40Z",
       "cadence_s":60,"stale_after_s":120,"feature_count":812,"retry_after_s":null,
       "detail":"websocket dropped; resubscribing"}
```

**`event: region_changed`** — active region switched; frontend clears all layers and awaits fresh snapshots.
```
event: region_changed
id: 1291
data: {"region_id":"gulf-of-oman","bbox":[56.5,22.0,62.0,26.5]}
```

**`event: ping`** — keep-alive comment/heartbeat from sse-starlette; frontend ignores. Interval from config.

### Reconnection semantics
`EventSource` auto-reconnects on drop. The server does not track per-client cursors; it re-sends full state on connect ([ADR-12](../docs/DECISIONS.md#adr-12--sse-reconnection)). Because the registry is the latest projection (PRD §1), full-state is always correct and history replay is meaningless. Rate-limited / error / reconnecting states ride `layer_status` events; the badge updates without any HTTP error.
