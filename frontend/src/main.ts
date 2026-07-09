import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/tokens.css';
import './styles/layout.css';
import { initMap } from './map/map';
import { fetchSnapshot, refreshAll } from './api/client';
import { initAviationLayer, updateAviationLayer, clearAviationLayer } from './map/layers/aviation';
import { initLandLayer, updateLandLayer, clearLandLayer } from './map/layers/land';
import { mountBadge } from './ui/badges';
import { mountConnectionBanner } from './ui/controls';
import { mountRegionSelector } from './ui/regionSelector';
import { loadLayers, type LayerLoadTask } from './app/loadLayers';
import { Store } from './state/store';
import { SseClient } from './sse/client';
import type { LayerSnapshot, LayerSnapshotMeta } from './state/types';

// Entry point (spec §1): bootstrap store -> map -> SSE client -> UI mount.
// The store is the single source of truth for layer state + connection
// state (spec §9); the SSE client is the live-update spine (spec §3),
// dispatching `snapshot`/`layer_status`/`region_changed` into the store's
// mutators. Renderers subscribe to store events (§9 "renderers subscribe,
// never poll") rather than owning their own fetch/poll loop.
const container = document.getElementById('map');
if (!container) {
  throw new Error('Zij: #map container not found');
}
const map = initMap(container);

const badgesContainer = document.getElementById('badges');
if (!badgesContainer) {
  throw new Error('Zij: #badges container not found');
}
const airBadge = mountBadge(badgesContainer, 'air');
const marineBadge = mountBadge(badgesContainer, 'marine');
const landBadge = mountBadge(badgesContainer, 'land');

const store = new Store();

const regionSelectorContainer = document.getElementById('region-selector');
if (!regionSelectorContainer) {
  throw new Error('Zij: #region-selector container not found');
}
mountRegionSelector(regionSelectorContainer, store);

// Region switch (spec §6): "all layer panes clear immediately" — the store's
// own state is cleared by `applyRegionChanged` (see state/store.ts), but the
// MapLibre GeoJSON sources are a separate piece of state the store doesn't
// own; clear them here. No-op if the sources haven't been added yet (map not
// yet loaded / layer never initialized) — see `clear*Layer`'s own guard.
store.on('region:changed', () => {
  clearAviationLayer(map);
  clearLandLayer(map);
});

// Air/land map sources+layers can only be added once the base style has
// fired `style.load` (map/map.ts uses the same event for `window.__zijMap`
// — see its comment for why `style.load`, not the tile-fetch-bound `load`,
// is the right readiness signal here). A `snapshot` event
// (full-state-on-connect) may arrive before that — buffer it and flush once
// the map is ready. `*Initialized` guards `initXLayer` (addSource, which
// throws if called twice) so it is safe to call the render path from more
// than one source (SSE push, the initial REST fetch below, and any manual
// refresh) without ever double-initializing.
let mapLoaded = false;
let airLayerInitialized = false;
let landLayerInitialized = false;
let pendingAirSnapshot: LayerSnapshot | null = null;
let pendingLandSnapshot: LayerSnapshot | null = null;

// Set the moment any SSE event lands for a domain (snapshot OR status —
// spec §3 ADR-12: full-state-on-connect means SSE always re-emits a fresh
// `snapshot` per enabled layer on (re)connect, so SSE is the canonical live
// source once it has spoken). Guards the one-time cold-start REST fetch
// below from clobbering an already-live SSE view with a possibly older REST
// response race — SSE and REST are not guaranteed to resolve in a fixed
// order (map `style.load` timing is network-dependent), so "last write wins"
// is not safe here; "SSE always wins once it has spoken" is.
let airSseReceived = false;
let landSseReceived = false;

function renderAirSnapshot(snapshot: LayerSnapshot): void {
  airBadge.update(snapshot.meta);
  if (!mapLoaded) {
    pendingAirSnapshot = snapshot;
    return;
  }
  if (!airLayerInitialized) {
    initAviationLayer(map, snapshot);
    airLayerInitialized = true;
  } else {
    updateAviationLayer(map, snapshot);
  }
}

function renderLandSnapshot(snapshot: LayerSnapshot): void {
  landBadge.update(snapshot.meta);
  if (!mapLoaded) {
    pendingLandSnapshot = snapshot;
    return;
  }
  if (!landLayerInitialized) {
    initLandLayer(map, snapshot);
    landLayerInitialized = true;
  } else {
    updateLandLayer(map, snapshot);
  }
}

// Mutators are the only writers (spec §9); renderers + badges are pure
// subscribers to the store's `snapshot:*`/`status:*` events.
store.on('snapshot:air', (payload) => {
  airSseReceived = true;
  renderAirSnapshot(payload as LayerSnapshot);
});
store.on('snapshot:land', (payload) => {
  landSseReceived = true;
  renderLandSnapshot(payload as LayerSnapshot);
});
store.on('status:air', (payload) => {
  airSseReceived = true;
  airBadge.update(payload as LayerSnapshotMeta);
});
store.on('status:land', (payload) => {
  landSseReceived = true;
  landBadge.update(payload as LayerSnapshotMeta);
});

// Marine badge only this slice — no marine map source/layer yet (deferred to
// step). It updates from meta alone on both full snapshots and meta-only
// status transitions (e.g. `reconnecting` on a dropped aisstream websocket).
store.on('snapshot:marine', (payload) => marineBadge.update((payload as LayerSnapshot).meta));
store.on('status:marine', (payload) => marineBadge.update(payload as LayerSnapshotMeta));

// Exactly one EventSource for the app's lifetime (spec §3) — the Retry
// action (below) re-runs `connect()`, which is the one sanctioned exception
// (the prior connection has already failed fatally by the time Retry shows).
const sseClient = new SseClient(store);
mountConnectionBanner(document.body, store, () => {
  sseClient.connect();
});

// Failure isolation (spec FR10, issue #20): each domain's fetch+render is an
// independent `LayerLoadTask` run through `loadLayers`, so one domain
// rejecting never blocks the other from rendering (see `app/loadLayers.ts`).
// This REST fetch runs alongside the SSE push above (not instead of it): it
// is what serves a cold start whose SSE snapshot hasn't arrived yet. SSE and
// REST are not guaranteed to resolve in a fixed order (map `style.load`
// timing is network-dependent), so each task's `render` is skipped if SSE
// has already spoken for that domain by the time the REST fetch resolves —
// otherwise a slow-resolving cold-start REST fetch could clobber an
// already-live SSE view with stale data (ADR-12: SSE is the canonical live
// source once connected).
map.on('style.load', () => {
  mapLoaded = true;
  if (pendingAirSnapshot) {
    const snapshot = pendingAirSnapshot;
    pendingAirSnapshot = null;
    renderAirSnapshot(snapshot);
  }
  if (pendingLandSnapshot) {
    const snapshot = pendingLandSnapshot;
    pendingLandSnapshot = null;
    renderLandSnapshot(snapshot);
  }

  const initialLoadTasks: LayerLoadTask[] = [
    {
      label: 'air',
      load: () => fetchSnapshot('air'),
      render: (snapshot) => {
        if (!airSseReceived) {
          renderAirSnapshot(snapshot as LayerSnapshot);
        }
      },
    },
    {
      label: 'land',
      load: () => fetchSnapshot('land'),
      render: (snapshot) => {
        if (!landSseReceived) {
          renderLandSnapshot(snapshot as LayerSnapshot);
        }
      },
    },
  ];
  void loadLayers(initialLoadTasks);
});

const refreshButton = document.querySelector<HTMLButtonElement>('[data-testid="refresh-all"]');
refreshButton?.addEventListener('click', () => {
  void (async () => {
    await refreshAll();
    // Fire-and-forget per spec §7 — the resulting status/snapshot rides SSE
    // in production. This REST re-fetch stays as a poll-once fallback for
    // environments with no live SSE stream (e.g. this app's own e2e harness);
    // it is reconciled through the same idempotent render path as the SSE
    // push, so the two never conflict.
    const refreshTasks: LayerLoadTask[] = [
      {
        label: 'air',
        load: () => fetchSnapshot('air'),
        render: (snapshot) => renderAirSnapshot(snapshot as LayerSnapshot),
      },
      {
        label: 'land',
        load: () => fetchSnapshot('land'),
        render: (snapshot) => renderLandSnapshot(snapshot as LayerSnapshot),
      },
    ];
    await loadLayers(refreshTasks);
  })().catch((err) => {
    console.warn('[zij] refresh failed:', err);
  });
});
