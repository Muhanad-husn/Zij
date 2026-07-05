# Spec — `sources/overpass.py` (Overpass PollAdapter)

**Purpose.** Land `PollAdapter` (§6.3, D4): runs whitelisted Overpass QL per feature class over the region bbox, captures `osm_base`, simplifies geometry (Douglas-Peucker, ≤5000 features), and returns `LayerSnapshot(domain=LAND)`. Cache interaction (serve-from-`land_cache`-when-fresh) is orchestrated by the scheduler + store; this adapter owns the network fetch + simplification.

## Public interface
```python
class OverpassAdapter(PollAdapter):
    domain = Domain.LAND
    source = "overpass"
    async def start(self) -> None; async def stop(self) -> None
    async def fetch(self, region: Region) -> LayerSnapshot   # always hits network; cache is scheduler/store's decision
```
`fetch` performs the live Overpass fetch and returns simplified features. The scheduler consults `store.get_land_cache` first and only calls `fetch` when the cache is stale (>24 h) or absent (ARCHITECTURE §3.3; store.md land_cache rules). On success the scheduler writes through `store.put_land_cache`.

## Internal design

### Query templates (§6.3 whitelist)
Bbox substituted as Overpass `(south,west,north,east)` from `region.bbox=[w,s,e,n]`. Every query header carries `[out:json][timeout:{cfg.timeout_s}][maxsize:{cfg.maxsize_bytes}]` (180 s, 512 MB from `[overpass]`).

Six feature-class queries (run per §6.3, partitioned — see below):

1. **border_control** — `node["barrier"="border_control"]({bbox});out;`
2. **aerodromes** — `(node["aeroway"="aerodrome"]({bbox});way["aeroway"="aerodrome"]({bbox}););out center;`
3. **ports/harbours** — `(node["harbour"]({bbox});way["harbour"]({bbox});way["landuse"="port"]({bbox}););out center;`
4. **rail stations/yards** — `(node["railway"~"^(station|yard)$"]({bbox});way["railway"~"^(station|yard)$"]({bbox}););out center;`
5. **major roads (ways)** — `way["highway"~"^(motorway|trunk|primary)$"]({bbox});out geom;`
6. **mainline rail (ways)** — `way["railway"="rail"]({bbox});out geom;`

`out geom` returns inline node coordinates (needed for LineString geometry); `out center` gives a representative point for node/area classes.

### Partitioning + mirror strategy
- **Sequential per feature class with a delay** (`0.5 s` between classes) — be kind to public mirrors (§6.3, §12). Not parallel: parallel bursts to one mirror is exactly what triggers throttling.
- **Mirror rotation:** iterate `cfg.mirrors` in order. On `429`/`504`/timeout for a class, advance to the next mirror and retry that class with exponential backoff: `delay = min(cfg.backoff_max_s, cfg.backoff_base_s * 2**attempt)` (base 5 s, max 300 s, `cfg.max_attempts=4`). Exhausting mirrors+attempts for any class → `UpstreamError` (scheduler falls back to warm cache, FR10).
- httpx timeout aligned to `timeout_s` + slack (e.g. `timeout_s + 30`).

### Parsing → Feature
- `source_id = f"{element.type}/{element.id}"` (e.g. `way/23895671`).
- `label = tags.get("name")` (may be null).
- `attrs = element.tags` **verbatim** (OSM tags, source-native, feature-schema.md).
- **Points** (nodes, or `out center` results): `geometry_type=POINT`, `geometry=None`, `lat/lon` from the node/center.
- **Ways with `geometry`:** `geometry_type=LINESTRING`, `geometry={"type":"LineString","coordinates":[[lon,lat],...]}` (RFC 7946 order, [ADR-11](../docs/DECISIONS.md#adr-11--geometry-wire-format-geojson)); `lat/lon` = midpoint vertex (label anchor). Closed ways from area classes → `POLYGON` with centroid as `lat/lon`.
- Deduplicate across classes by `source_id` (a way can match two class queries — keep first).
- `timestamp_source = osm_base` (see below) for **every** land feature; `position_age_s = now - osm_base` (large by nature; feature-schema.md nullability table).

### `osm_base` capture (FR4)
Each Overpass response's `osm3s.timestamp_osm_base` → parse to UTC, use as the layer's and every feature's `timestamp_source`. When queries span multiple responses/mirrors, use the **oldest** `osm_base` across responses (most conservative freshness claim). This is the value displayed as the land source timestamp (FR4 acceptance), and is written to `land_cache.osm_base`.

### Geometry simplification (Douglas-Peucker)
- Via **shapely** (`shapely.simplify(geom, tolerance, preserve_topology=False)`), tolerance `cfg.simplify_tolerance_deg = 0.0005` (~55 m at the equator) from `[layers.land]`. Applied to LineString/Polygon before building the Feature; points untouched.
- **Target ≤ `cfg.max_rendered_features` (5000).** If the simplified feature count still exceeds the cap, apply this **deterministic drop priority** (drop lowest-value first until ≤5000):
  1. `highway=primary` ways,
  2. `railway=rail` (non-junction) ways,
  3. `highway=trunk` ways.
  Never drop point classes (border_control, aerodrome, port/harbour, rail station/yard) or `highway=motorway` — these are the logistics anchors the land layer exists to show. Within a drop tier, order by ascending geometry length (drop shortest fragments first — they contribute least to the network picture). Deterministic so the same region always yields the same set (cacheable, reproducible).

### Concurrency
Pure awaits + shapely CPU work. Simplification runs once per 24 h on ≤5000 features — bounded, fits a tick ([ADR-8](../docs/DECISIONS.md#adr-8--concurrency-pure-asyncio)); wrap in `to_thread` only if measured to stall the loop (measure-don't-speculate).

## Cache interaction (scheduler/store contract)
- Scheduler: on region activation, `store.get_land_cache(region_id)`; if `now - fetched_at < land.cadence_s` (24 h, floor 1 h) serve it directly (<2 s, FR4) — **no `fetch`**. Else call `fetch`, then `store.put_land_cache` with `geojson` (render-ready FeatureCollection), `osm_base`, `fetched_at=now`, `feature_count` (storage.md).
- `land_cache.osm_base` (not `fetched_at`) is the displayed source ts (FR4).

## Failure modes
`429`/`504`→retry-with-mirror-rotation then `UpstreamError` if exhausted; other `5xx`/timeout→`UpstreamError`; malformed JSON→`ParseError`; Overpass has no auth (no `AuthError`). On any `UpstreamError`, scheduler keeps serving stale `land_cache` as `cached-fallback` (FR8/FR10) rather than blanking the layer.

## Configuration consumed
`[overpass]` (`mirrors`, `timeout_s`, `maxsize_bytes`, `backoff_base_s`, `backoff_max_s`, `max_attempts`); `[layers.land]` (`cadence_s`, `cadence_floor_s`, `simplify_tolerance_deg`, `max_rendered_features`, `custom_bbox_cap_sq_deg`).

## Acceptance criteria
- [ ] **FR4** — first-ever region load performs the Overpass fetch with a `loading` status (scheduler); subsequent loads serve from `land_cache` in <2 s.
- [ ] **FR4** — the land layer's displayed source timestamp is the Overpass `osm_base`, not `fetched_at`.
- [ ] **§6.3** — only whitelisted classes are queried; secondary roads and below never fetched.
- [ ] **§6.3/NFR4** — simplified output ≤5000 features via Douglas-Peucker at tol 0.0005°; over-cap drops follow the deterministic priority; motorway + all point anchors always retained.
- [ ] **§6.3/§12** — `429`/`504` rotates mirrors with 5→300 s exponential backoff (max 4 attempts) before surfacing `UpstreamError`; sequential per-class fetch with delay.
