# Contract — Frontend Specification

Implements PRD §1.1 (visual identity), §8 FR1–FR10, §9 NFR4/NFR6, on the stack fixed by [ADR-3](../docs/DECISIONS.md#adr-3--frontend-vite--vanilla-ts--maplibre): **Vite + vanilla TypeScript + MapLibre GL JS, no framework**. Buildable against [api.md](../contracts/api.md) and [feature-schema.md](../contracts/feature-schema.md) alone. One map screen (ADR-3) — every section below stays inside that boundary; a second screen is a scope alarm (PRD §11).

Cross-refs: [ARCHITECTURE.md](../docs/ARCHITECTURE.md), [DECISIONS.md](../docs/DECISIONS.md), [contracts/api.md](../contracts/api.md), [contracts/feature-schema.md](../contracts/feature-schema.md), [contracts/config.md](../contracts/config.md).

---

## 1. Module structure

```
frontend/
  index.html
  vite.config.ts
  tsconfig.json
  package.json
  public/
    fonts/            Archivo + Spline Sans Mono, woff2, bundled (no CDN — v2 offline desktop)
    icons/             source SVGs for the SDF icon atlas: aircraft, vessel, port, airport,
                       border-crossing, rail-station
  src/
    main.ts            entry: bootstrap store → map → SSE client → UI mount
    config.ts          API base path, tick interval, SSE retry constants
    state/
      store.ts         AppState + typed event-emitter (§9)
      types.ts         wire types mirroring feature-schema.md / api.md verbatim
      derive.ts        client-side age/de-emphasis/drop computation (§2, §9)
    api/
      client.ts        fetch wrappers: regions, estimate, activate, toggle, refresh,
                       caveats, raw-feature, presets (one function per api.md endpoint)
    sse/
      client.ts        EventSource wrapper: dispatch, reconnect/lost detection (§3)
    map/
      map.ts            MapLibre init, custom style, source/layer registration, attribution
      icons.ts          SDF icon atlas load (map.addImage) at startup
      layers/
        aviation.ts      air source + symbol layers + tick-driven restyle (§2)
        marine.ts        marine source + symbol/circle layers + tick-driven restyle (§2)
        land.ts          land line + point layers, static per snapshot (§2)
      popup.ts           one shared maplibregl.Popup + per-domain content builders
    ui/
      badges.ts          layer badge DOM (§4)
      caveatPanel.ts      caveat panel DOM (§5)
      regionSelector.ts   predefined + custom bbox flow (§6)
      controls.ts         refresh-all, connection-lost banner (§7)
      layout.ts           mounts sidebar/topbar/bottom-sheet per breakpoint (§7)
    styles/
      tokens.css          CSS custom properties: palette + type (§8)
      layout.css          badges/panel/controls/wireframe layout
      fonts.css           @font-face declarations
```

Nothing here is a component framework — `ui/*` modules export `mount(container): void` functions that build DOM nodes imperatively and subscribe to `state/store.ts`. This is deliberately "boring" per ADR-3; if this sprawls past a few hundred lines total, that is the ADR-3 scope-alarm trigger, not a cue to add a framework.

### Build (ADR-7, ADR-3)

- **Dev:** `vite dev`; `vite.config.ts` proxies `/api` (including `/api/events`) to the FastAPI process:
  ```ts
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: false } } }
  ```
  `ws: false` is correct — SSE is a plain streaming HTTP GET, not a websocket ([ADR-2](../docs/DECISIONS.md#adr-2--sse-via-sse-starlette)). The proxy must not buffer/compress the response; Vite's default `http-proxy` streams through fine. `sse_ping_s=15` ([config.md](../contracts/config.md)) keeps the connection under any reasonable idle timeout.
- **Prod:** `vite build` → `frontend/dist`; FastAPI mounts it via `StaticFiles` at `/`, `/api/*` takes precedence (ADR-7). Single origin → no CORS, SSE needs no preflight.
- No CDN dependencies anywhere (fonts, tiles style JSON fetched from the configured provider at runtime are the only network fetch besides `/api`).

---

## 2. Map and layer rendering

**One MapLibre `Map` instance, one custom style.** Per domain: **one GeoJSON source, updated via `source.setData()`** on every `snapshot` event and every client tick (§9) — never added/removed, never per-feature `maplibregl.Marker()` DOM elements (NFR4). All feature-count-heavy rendering goes through symbol/circle/line layers, which are GPU-batched.

### Wire → GeoJSON

Feature.geometry_type is lowercase (`point`/`linestring`/`polygon`); GeoJSON `geometry.type` is capitalized. For points, wire `geometry` is `null` ([feature-schema.md](../contracts/feature-schema.md#geometry)) — the frontend constructs `{type:"Point", coordinates:[lon,lat]}` itself. For line/polygon, wire `geometry` is already valid GeoJSON — use as-is. `attrs`, `integrity_flags`, `status`, `position_age_s`, `timestamp_source`, `timestamp_fetched` all become GeoJSON `properties` (flattened alongside `attrs` object) so MapLibre expressions can reach them; nested values under `attrs` are addressed with the two-argument `["get", "highway", ["get", "attrs"]]` form.

### Aviation

- Symbol layer, `icon-image` = a single SDF aircraft glyph, `icon-rotate: ["get", "true_track_deg"]` (from `attrs.true_track_deg`), `icon-rotation-alignment: "map"`. `icon-color` = `--zij-brass` (air domain color).
- **De-emphasis (FR2):** a state vector older than 60 s (its own `time_position`) renders reduced-opacity. `icon-opacity` is a data-driven expression against a client-computed `deemphasized` boolean property (see §9/`derive.ts`): a feature is de-emphasized if wire `status == "stale"` **OR** the client-computed age exceeds `[layers.air].deemphasize_after_s` (60 s). The renderer does not rely solely on the wire `status` field because SSE only pushes every `cadence_s` (600 s for air), too coarse for smooth de-emphasis.
- **Popup (FR2):** ICAO24 (`source_id`), callsign (`label`), altitude (`attrs.altitude_m`, `attrs.geo_altitude_m`), velocity (`attrs.velocity_ms`), vertical rate (`attrs.vertical_rate_ms`), position source (`attrs.position_source`), position age (`position_age_s`, live-incremented client-side, not just the value at fetch time).
- Grounded aircraft (`attrs.on_ground === true`) render without rotation (heading is meaningless on the ground) — a minor, non-normative touch.

### Marine

- Symbol layer, single SDF vessel glyph, `icon-rotate` = `attrs.cog_deg` (COG rotation per FR3), falling back to `attrs.heading_deg` if `cog_deg` is null, else no rotation (icon renders upright/neutral — `attrs.sog_kn`/`cog_deg` may legitimately be absent, [feature-schema.md nullability](../contracts/feature-schema.md#nullability-rules-per-domain)). `icon-color` = `--zij-teal`.
- **De-emphasis (FR3):** not heard from in 30 min → reduced opacity; in 2 h → dropped from the projection entirely (removed from the GeoJSON before `setData`). Both are client-tick-driven (§9), thresholds sourced from `config.layers.marine.deemphasize_after_s` / `drop_after_s` ([config.md](../contracts/config.md)) via `GET /api/config`.
- **Integrity markers (FR9, NFR3 — never hidden):** a second circle layer, filtered by `["in", "spoof_suspect_on_land", ["get", "integrity_flags"]]`, draws a hollow warning ring (stroke-only circle, no fill) around the vessel icon, rendered above the base symbol layer. A third layer (different stroke color/dash) does the same for `implausible_kinematics`. A vessel can carry both flags simultaneously — both rings render concentrically. These layers are filters over the *same* source; no separate fetch, no separate marker.
- **Popup (FR3):** MMSI (`source_id`), name/callsign (`label`, may be null), SOG (`attrs.sog_kn`), COG (`attrs.cog_deg`), position age. If `integrity_flags` is non-empty, the popup header shows the flag name(s) inline (not just the map ring) so touch users without hover access still see it.

### Land

- Two static layers per feature-class group, built from the single land GeoJSON source (features carry OSM tags verbatim in `attrs`):
  - **Line layer** (roads): `filter: ["has", "highway"]`, `line-color`/`line-width` stepped by `attrs.highway` (motorway thickest, then trunk, then primary), all in `--zij-dun` at reduced saturation ("muted dun palette" — context, not telemetry).
  - **Line layer** (rail): `filter: ["==", ["get","railway"], "rail"]`, dashed (`line-dasharray`), thinner, same dun family.
  - **Point layer**: symbol layer for ports (`attrs.harbour`/`attrs.landuse=="port"`), airports (`attrs.aeroway=="aerodrome"`), border crossings (`attrs.barrier=="border_control"`), stations/yards (`attrs.railway` station/yard tags) — one SDF glyph per feature-class, `icon-color: --zij-dun`, selected by a `match` expression over the relevant tag.
- Land is visually distinct from telemetry by construction: muted/desaturated dun, no rotation, no popups showing "position age" as if it were live (label reads "map data as of `osm_base`", not "last seen").
- Land's source is rebuilt once per snapshot (at most daily, FR4) — no client tick needed; it is the one domain exempt from §9's ticking recompute.

### Performance budget (NFR4: 5,000 land + 500 air + 1,000 marine, mid-range hardware)

- **One GeoJSON source per domain**, `setData()` on update — never re-created. MapLibre diffs internally; this is the standard high-feature-count pattern.
- **No per-feature DOM markers.** Every icon is a symbol-layer feature; MapLibre batches these into as few draw calls as the atlas allows.
- **Single SDF icon atlas** (`map.addImage(id, data, {sdf: true})` per glyph, loaded once at startup in `icons.ts`): one shape per glyph, tinted per-domain via `icon-color`, so 6 source SVGs cover all three domains' status/flag variants without needing a colored PNG per state.
- **One shared `Popup` instance**, opened on a layer `click` handler via `map.on('click', layerId, ...)`, not one `Popup` per feature.
- **Tick-driven restyle (§9) is cheap:** recomputing `deemphasized`/`dropped` booleans over ≤1,500 features (air+marine combined) every 5–10 s and calling `setData` again is well inside a mid-range frame budget; it does not touch the network.

### Base map

Vector tiles from **OpenFreeMap** (PRD §6.4). OpenFreeMap's stock named styles (Liberty/Bright/Positron) are light-themed; none matches the night-ink identity. The frontend therefore uses OpenFreeMap's tiles as a **source only** (Shortbread vector schema) with a **hand-authored custom style** (background/water/landuse/roads/labels recolored to `--zij-ink` and muted grays) — the standard way to consume shortbread-schema tiles with custom styling; no fork or self-hosting needed for v1. **`AttributionControl`** (required, OSM + OpenFreeMap credit) is always present, non-collapsible on desktop, compact-collapsible on narrow viewports per MapLibre's built-in control option.

> NOTE: Icon-rotation source field for marine (`cog_deg` vs `heading_deg`) is not disambiguated in feature-schema.md beyond "COG rotation" in FR3 prose. Resolution adopted above: prefer `cog_deg`, fall back to `heading_deg`, else no rotation.

---

## 3. SSE client

Thin wrapper over the browser-native `EventSource` (no reconnect/backoff reimplementation — that's exactly the "reinventing a solved problem" ADR-2 already rejected once, for the server side; the client side gets the same native benefit for free).

```ts
class SseClient {
  private es: EventSource;
  constructor(private store: Store, url = '/api/events') {
    this.es = new EventSource(url);
    this.es.addEventListener('snapshot', e => {
      const snap: LayerSnapshot = JSON.parse((e as MessageEvent).data);
      store.applySnapshot(snap.meta.layer, snap);
    });
    this.es.addEventListener('layer_status', e => {
      const meta: LayerSnapshotMeta = JSON.parse((e as MessageEvent).data);
      store.applyLayerStatus(meta.layer, meta);
    });
    this.es.addEventListener('region_changed', e => {
      store.applyRegionChanged(JSON.parse((e as MessageEvent).data));
    });
    // 'ping' — no listener needed; it's a comment/heartbeat sse-starlette sends,
    // EventSource surfaces it only if explicitly listened for. Absence of any
    // event for > sse_ping_s * 2 is what onerror/readyState already covers below.
    this.es.onopen = () => store.setConnection('open');
    this.es.onerror = () => {
      // readyState CONNECTING: native auto-retry in flight — show "reconnecting" banner.
      // readyState CLOSED: fatal (e.g. non-2xx / bad content-type on connect) — native
      // retry will NOT resume; surface a manual "Retry" action that re-runs connect().
      store.setConnection(this.es.readyState === EventSource.CLOSED ? 'failed' : 'lost');
    };
  }
  reconnect(url = '/api/events') { this.es.close(); /* re-run constructor body */ }
}
```

- **Connection-lost UI:** `store.connection ∈ {'connecting','open','lost','failed'}` drives a single global banner (`ui/controls.ts`) — `lost` shows "Reconnecting…" (non-blocking, map stays interactive on last-known state); `failed` shows a "Connection failed — Retry" button.
- **Full-state-on-connect ([ADR-12](../docs/DECISIONS.md#adr-12--sse-reconnection)):** on every (re)connect the server re-emits a `snapshot` per enabled layer before any incremental event — the client does nothing special to handle reconnects beyond clearing the banner on the next received event; `applySnapshot` is already an idempotent full replace.
- Exactly **one** `EventSource` is opened for the app's lifetime (per `/api/events` contract — "the frontend opens exactly one `EventSource`").

---

## 4. Layer badges and status UI (FR7)

One badge per domain (air/marine/land), always visible (§7 layout). Badge shows: domain color chip, `LayerStatus` color/label, both timestamps (UTC, labeled — NFR6), feature count, and is the entry point to the caveat panel (§5).

| `LayerStatus` | Badge color (`--status-*`) | Label shown | Notes |
|---|---|---|---|
| `live` | `--status-live` (green) | "Live" | |
| `stale` | `--status-stale` (amber-yellow) | "Stale · {age}" | source ts > 2×cadence (FR7, layer-level) |
| `loading` | `--status-loading` (blue, pulsing) | "Loading…" | |
| `rate-limited` | `--status-rate-limited` (orange) | "Rate-limited · retry in {retry_after_s}s" | countdown ticks client-side from `retry_after_s` |
| `error` | `--status-error` (red) | "Error" | `detail` shown on hover/expand |
| `cached-fallback` | `--status-cached-fallback` (muted violet) | "Cached · {age}" | age from `timestamp_fetched` |
| `reconnecting` | same as `loading` (grouped, per [feature-schema.md LayerStatus note](../contracts/feature-schema.md#layerstatus-note)) | "Reconnecting…" | marine-only |

Both timestamps (`timestamp_fetched`, `timestamp_source`) render as `HH:MM:SS UTC` (NFR6 — never local time, always labeled). Badge layout:

```
[●] AIR            live
    fetched 09:12:03 UTC
    source  09:11:58 UTC
    1 feature
    [ Toggle ] [ Refresh ↻ ] [ Caveats ⓘ ]
```

Badge is built once per domain and updated imperatively on `status:{domain}` / `snapshot:{domain}` store events (no re-render of the whole badge tree). The "Caveats ⓘ" control is always present and always enabled — it is the FR9 entry point, reachable regardless of current status (including `error`, so a broken layer's caveats — e.g., coverage limits — remain visible).

---

## 5. Caveat panel (FR9)

One panel component (`ui/caveatPanel.ts`), opened from any badge's "Caveats" control, one instance reused across domains (content swapped, not re-mounted).

- **Content:** `GET /api/layers/{domain}/caveats` ([api.md](../contracts/api.md#get-apilayersdomaincaveats)) — static caveat bullets (verbatim, not paraphrased) plus `active_flags` counts (e.g. "3 marine positions currently flagged spoof-suspect"). Fetched on open; cached in `store.caveats[domain]` and refreshed opportunistically alongside the layer's own refresh (not on every snapshot — caveat text is static, only counts move, and staleness of a count by one cadence tick is immaterial).
- **Layout:** slide-in panel (right side desktop, bottom sheet mobile — §7), header = domain name + domain color accent bar, body = bullet list, footer = active-flag counts + close button.
- **Behavior (FR9 acceptance):** reachable from every badge; **no "don't show again" control anywhere** — closing hides the panel for that session only, and the badge's Caveats button remains the only way back in every single time. This is the one interaction in the whole app that intentionally has no persistent-dismiss state, by design.

---

## 6. Region selector (FR1)

`ui/regionSelector.ts`, anchored in the top bar (§7).

**Predefined path:** dropdown populated from `GET /api/regions` (label + `aviation_credit_cost` shown inline per option). Selecting one calls `POST /api/regions/activate {region_id}` directly — no client-side estimate step, since predefined regions are pre-costed (config.md).

**Custom bbox path:**
1. "Custom bbox…" opens a small panel with two input modes: **draw-on-map** (a minimal custom rectangle-drag handler — mousedown → mousemove(preview rectangle via a temporary GeoJSON source) → mouseup → bbox; deliberately not a full draw-toolkit dependency, since exactly one shape (axis-aligned rectangle) is ever needed — pulling in `mapbox-gl-draw`/a MapLibre draw fork would be over-scoped for this one interaction, revisit only if more shapes are ever required) and **enter coordinates** (four number inputs: west/south/east/north — precise, keyboard-only, works without drag on touch).
2. On every bbox change (debounced ~300 ms), call `POST /api/regions/estimate {bbox}` ([api.md](../contracts/api.md#post-apiregionsestimate)).
3. Render the response verbatim: `area_sq_deg`, `aviation_credit_cost`, and per-layer `layer_caps[...]` — if any `ok:false`, show that layer's cap-violation message inline (FR1 acceptance: "a message naming the cap") and disable the Confirm button. **All math (area, credit cost, cap comparison) is server-computed and only formatted for display here — no client-side duplication of the cost/cap arithmetic.**
4. Confirm → `POST /api/regions/activate {bbox, label, save_as_preset}`; a `422` (server re-validates independently) is handled identically to step 3's inline error.
5. On `region_changed` (SSE), all layer panes clear immediately (stale features never linger under the new region's name) and wait for fresh `snapshot` events.

Per [api.md](../contracts/api.md#post-apiregionsestimate), a failing `layer_caps` entry carries a `message` naming the cap (present when `ok:false`); the frontend renders it directly. As a defensive fallback it can compose `"{layer} exceeds its {cap_sq_deg} sq° cap"` from the always-present fields if a `message` is ever absent.

---

## 7. Controls and screen layout

**Layer toggles (FR5):** one on/off control per badge (§4) — `POST /api/layers/{domain}/toggle {enabled}`. Disabling immediately stops rendering that domain's source (clear GeoJSON) and grays the badge; per contract, a disabled layer consumes no upstream budget, and the frontend reflects that by simply not expecting further SSE events for it until re-enabled.

**Refresh (FR6):** a per-badge refresh button (`POST /api/layers/{domain}/refresh`) and one global "Refresh all" control in the top bar (`POST /api/refresh`). Both are fire-and-forget (`202`); the resulting status ride SSE (`loading` → `live`/etc.) — the frontend does not poll for completion. Buttons disable for the brief window the layer sits in `loading` to make coalescing visible rather than inviting a flood of manual clicks (the actual coalescing guarantee is backend's, FR6).

**Screen layout — one map screen (ADR-3), two breakpoints:**

Desktop (≥ 900 px):
```
┌──────────────────────────────────────────────────────────────────┐
│ Zij   [Region: Strait of Hormuz ▾]  [Custom bbox…]  [Refresh all ↻]│
├───────────────┬────────────────────────────────────────────────────┤
│ ● AIR   live   │                                                    │
│  fetched 09:12 │                                                    │
│  source  09:11 │                                                    │
│  [⏻][↻][ⓘ]     │                       M A P                       │
├───────────────┤                                                     │
│ ● MARINE live  │                                                    │
│  ...   [⏻][↻][ⓘ]                                                    │
├───────────────┤                                                     │
│ ● LAND  live   │                                                    │
│  ...   [⏻][↻][ⓘ]                                                    │
├───────────────┤                                                     │
│ conn: ● open   │                                                    │
└───────────────┴──────────────────────────────────────────┬──────────┘
                                       © OpenStreetMap contributors · OpenFreeMap
```

Narrow / mobile (< 600 px) — badges collapse to a tappable chip strip; detail lives in a bottom sheet:
```
┌──────────────────────────────┐
│ Zij        [Region ▾]   [☰]  │
├──────────────────────────────┤
│ [● AIR] [● MARINE] [● LAND]  │  ← tap a chip to open its sheet
│                               │
│             M A P             │
│                               │
├──────────────────────────────┤
│ © OSM contributors             │
└──────────────────────────────┘
  tap chip →
┌──────────────────────────────┐
│ AIR — live                    │
│ fetched 09:12:03 UTC          │
│ source  09:11:58 UTC          │
│ [ Toggle ] [ Refresh ]        │
│ [ View caveats ]              │
└──────────────────────────────┘
```

Connection-lost banner (§3) overlays the top bar full-width when `connection ∈ {lost, failed}`, on both breakpoints.

---

## 8. Visual identity application (PRD §1.1)

```css
:root {
  /* palette */
  --zij-ink:          #101D30;   /* base background, night ink */
  --zij-ink-raised:   #16283F;   /* panels/badges, one step lighter */
  --zij-brass:        #D99A3B;   /* air domain */
  --zij-teal:         #4E9DB4;   /* marine domain */
  --zij-dun:          #A38B62;   /* land domain */
  --zij-text:         #EDE6D6;   /* warm off-white, on-ink contrast */
  --zij-text-muted:   #9AA6B8;

  /* status scale — deliberately distinct hues from the domain scale above,
     so a status color is never mistaken for a domain color */
  --status-live:            #4CAF7D;
  --status-stale:           #E8C468;
  --status-loading:         #6FA8DC;
  --status-rate-limited:    #E08A3C;
  --status-error:           #D9534F;
  --status-cached-fallback: #9B8AA6;
  --status-reconnecting:    var(--status-loading);

  /* type */
  --font-ui:   'Archivo', system-ui, sans-serif;
  --font-mono: 'Spline Sans Mono', ui-monospace, monospace;
}
```

- **Domain color coding is the same variable everywhere**: aircraft/vessel icon `icon-color`, land line/point `icon-color`/`line-color`, the badge's domain chip, and the caveat panel's header accent bar all read `--zij-brass`/`--zij-teal`/`--zij-dun` for their respective domain — one source of truth, no per-component re-declaration.
- **Status color is a separate scale** (table above) applied only to badges and the connection banner — never to map icons, so "this vessel is de-emphasized" (opacity, a domain-colored icon) and "this layer's fetch is rate-limited" (badge color) stay visually distinct concepts, matching the FeatureStatus/LayerStatus split in the schema.
- **Typography:** Archivo for all UI chrome (badges, buttons, panel text, region selector); Spline Sans Mono for anything tabular/numeric — both timestamps, lat/lon, credit-cost figures, countdowns — so columns of numbers align. Both fonts ship as local `woff2` under `public/fonts/`, loaded via `@font-face` in `fonts.css`; **no CDN reference**, per the v2 offline-capable-desktop requirement (PRD §1.1, D1).
- زيج naskh wordmark/lockup is a static asset (app icon / about panel), not part of the interactive UI chrome — out of scope for this spec beyond noting it exists (PRD §1.1 `zij_mark.svg`/`zij_lockup.svg`).

---

## 9. State handling

**Single app-state object**, held in a hand-rolled typed event-emitter (~20 lines — this is the one place ADR-2's "don't reinvent a solved problem" reasoning does *not* apply: a pub-sub over an in-memory object is not a solved problem with sharp edges the way SSE framing/heartbeats are; hand-rolling it keeps the "no framework" promise literal. A 200-byte library like `mitt` is an acceptable drop-in swap if preferred — non-load-bearing choice).

```ts
type Domain = 'air' | 'marine' | 'land';

interface LayerState {
  enabled: boolean;
  meta: LayerSnapshotMeta | null;
  features: Feature[];        // last snapshot's features, post client-tick derivation
  receivedAt: number;         // Date.now() when this snapshot was applied — tick basis
}

interface AppState {
  activeRegion: RegionInfo | null;
  layers: Record<Domain, LayerState>;
  connection: 'connecting' | 'open' | 'lost' | 'failed';
  caveats: Partial<Record<Domain, CaveatResponse>>;
}

class Store {
  private state: AppState;
  private listeners = new Map<string, Set<(payload: unknown) => void>>();
  on(event: string, fn: (payload: unknown) => void) { /* ... */ }
  private emit(event: string, payload?: unknown) { /* ... */ }

  applySnapshot(domain: Domain, snap: LayerSnapshot) { /* replace, emit `snapshot:${domain}` */ }
  applyLayerStatus(domain: Domain, meta: LayerSnapshotMeta) { /* meta-only, emit `status:${domain}` */ }
  applyRegionChanged(payload: { region_id: string; bbox: number[] }) { /* clear all layers, emit `region:changed` */ }
  setConnection(c: AppState['connection']) { /* emit `connection` */ }
  toggleLayer(domain: Domain, enabled: boolean) { /* optimistic local set, POST, reconciled by next status event */ }
  tick(now: number) { /* recompute de-emphasis/drop for air+marine, emit `tick:air` / `tick:marine` */ }
}
```

**Mutators:** SSE events (`applySnapshot`, `applyLayerStatus`, `applyRegionChanged`) and user actions (`toggleLayer`, region activation, refresh — the latter two don't mutate state directly, they wait for the resulting SSE event) are the *only* writers. A `setInterval` (~5–10 s, `config.ts`) calls `store.tick(Date.now())`.

**Renderers subscribe, never poll:** `map/layers/aviation.ts` subscribes to `snapshot:air` and `tick:air`; `marine.ts` to `snapshot:marine`/`tick:marine`; `land.ts` to `snapshot:land` only (no tick — §2); `ui/badges.ts` to `status:*`/`snapshot:*` (for feature counts); `ui/regionSelector.ts` to `region:changed`; `ui/controls.ts` to `connection`.

**De-emphasis/drop threshold sourcing.** Per-feature de-emphasis/drop is a *feature*-level concept keyed off the layer's configured `deemphasize_after_s`/`drop_after_s` — distinct from the *layer*-level `LayerStatus.STALE` (2× cadence, FR7). `FeatureStatus.STALE` ([feature-schema.md](../contracts/feature-schema.md#enums)) is stamped by the adapter when `position_age_s` exceeds that same `deemphasize_after_s` at snapshot time. The frontend de-emphasizes a feature if the wire `status == "stale"` **OR** its client-computed age exceeds the threshold: `state/derive.ts` recomputes age from `position_age_s` + elapsed wall-clock since `timestamp_fetched` and compares against air → `[layers.air].deemphasize_after_s` (60 s) and marine → `[layers.marine].deemphasize_after_s`/`drop_after_s`, all from `GET /api/config`. Client-side ticking is required regardless, since SSE only pushes every `cadence_s` (600 s for air) — too coarse for a smooth de-emphasis UX.

**`GET /api/config` layers shape.** Per [api.md](../contracts/api.md#get-apiconfig), the `layers` object mirrors [config.md](../contracts/config.md)'s per-layer tables as JSON — `{air: {enabled, cadence_s, cadence_floor_s, deemphasize_after_s, stale_multiplier, custom_bbox_cap_sq_deg}, marine: {..., deemphasize_after_s, drop_after_s}, land: {..., simplify_tolerance_deg, max_rendered_features}}` — so the frontend reads thresholds from one source without hardcoding.

---

## 10. Acceptance criteria (frontend-owned)

- [ ] **FR1** — Region dropdown lists all predefined regions + presets (`GET /api/regions`); custom bbox exceeding a cap is rejected with the cap-naming message before activation; credit-cost estimate is shown and is server-sourced, not recomputed client-side.
- [ ] **FR2** — Aircraft render within 5 s of the `snapshot` SSE event for ≤ 500 states; a state vector older than 60 s renders de-emphasized (client-tick-derived, §9); popup shows ICAO24/callsign/altitude/velocity/vertical rate/position source/age; `rate-limited` badge shown on 429 with retry countdown.
- [ ] **FR3** — Marine popup shows MMSI/name/SOG/COG/age; vessels de-emphasized at 30 min, dropped at 2 h (client-tick, config-sourced thresholds); `reconnecting` status renders distinctly (grouped with loading family per schema note) on websocket drop.
- [ ] **FR4** — Land layer renders styled lines (motorway/trunk/primary hierarchy + dashed rail) and point icons (ports/airports/border crossings/stations), visually muted-dun/context-only; displayed source timestamp is `osm_base`, not fetch time.
- [ ] **FR5** — Per-domain toggle stops rendering and grays the badge immediately; disabled layers generate no further SSE expectation.
- [ ] **FR6** — Per-layer and global "Refresh now" controls present; reflect `loading` via SSE without client-side polling.
- [ ] **FR7** — Badge renders all seven `LayerStatus` values with the color/label mapping in §4, plus both `timestamp_fetched`/`timestamp_source` in UTC.
- [ ] **FR8** — On cold start, `cached-fallback` badge shows true age (`now - timestamp_fetched`) before any live data arrives.
- [ ] **FR9** — Spoof-suspect and implausible-kinematics markers always render (never conditionally hidden, NFR3); caveat panel reachable from every badge in every status; no persistent-dismiss control exists anywhere for it.
- [ ] **FR10** — One domain's `error`/`rate-limited` status never blocks another domain's source from rendering (independent sources/subscriptions, independent badges).
- [ ] **FR11** (P1, designed now) — Raw-payload popup toggle calls `GET /api/features/{domain}/{source_id}/raw`; presets list/create/delete wired to `/api/presets`.
- [ ] **NFR4** — Interactive at 5,000 land + 500 air + 1,000 marine features on mid-range hardware: verified via one GeoJSON source per domain + `setData`, SDF icon atlas, zero per-feature DOM markers, one shared popup instance.
- [ ] **NFR6** — Every displayed timestamp is UTC, explicitly labeled ("UTC" or trailing "Z" made visible); no local-time conversion anywhere in the UI.
- [ ] Attribution control (OSM + OpenFreeMap) always visible, per §2/PRD §6.4.
