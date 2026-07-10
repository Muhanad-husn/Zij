import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/tokens.css';
import './styles/layout.css';
import { initMap } from './map/map';
import { fetchConfig, fetchSnapshot, refreshAll, refreshLayer } from './api/client';
import { initAviationLayer, updateAviationLayer, clearAviationLayer } from './map/layers/aviation';
import { initLandLayer, updateLandLayer, clearLandLayer } from './map/layers/land';
import { initMarineLayer, updateMarineLayer, tickMarineLayer, clearMarineLayer } from './map/layers/marine';
import { initMarinePopup } from './map/popup';
import { mountBadge } from './ui/badges';
import { mountCaveatPanel } from './ui/caveatPanel';
import { mountConnectionBanner } from './ui/controls';
import { mountRegionSelector } from './ui/regionSelector';
import { loadLayers, type LayerLoadTask } from './app/loadLayers';
import { Store } from './state/store';
import { SseClient } from './sse/client';
import { TICK_INTERVAL_MS } from './config';
import type { Domain, LayerSnapshot, LayerSnapshotMeta, WireFeature } from './state/types';

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

const store = new Store();

// Toggle/Refresh (spec §7 FR5/FR6) — one pair of handlers per domain, wired
// into each badge's buttons. Toggle reads the *current* enabled state off the
// store (not the DOM) and asks for its flip; `Store.toggleLayer` is the sole
// mutator (optimistic local set + fire-and-forget POST, §9). Refresh is
// fire-and-forget too — the resulting `loading` -> `live` transition rides
// SSE only (`store.on('status:*'/'snapshot:*')` below), never a REST re-fetch.
function makeToggleHandler(domain: Domain): () => void {
  return () => {
    const current = store.getState().layers[domain].enabled;
    store.toggleLayer(domain, !current);
  };
}
function makeRefreshHandler(domain: Domain): () => void {
  return () => {
    void refreshLayer(domain).catch((err) => {
      console.warn(`[zij] refreshLayer(${domain}) failed:`, err);
    });
  };
}

// Caveat panel (spec §5, FR9) — ONE instance for the app's lifetime, mounted
// to `document.body` so it can overlay the whole screen (slide-in
// right/bottom-sheet, §5/§7) rather than being clipped by #badges' layout.
// Every badge's Caveats button opens this same instance for its own domain.
const caveatPanel = mountCaveatPanel(document.body);
function makeCaveatsHandler(domain: Domain): () => void {
  return () => {
    void caveatPanel.open(domain);
  };
}

const badgesContainer = document.getElementById('badges');
if (!badgesContainer) {
  throw new Error('Zij: #badges container not found');
}
const airBadge = mountBadge(badgesContainer, 'air', {
  onToggle: makeToggleHandler('air'),
  onRefresh: makeRefreshHandler('air'),
  onCaveats: makeCaveatsHandler('air'),
});
const marineBadge = mountBadge(badgesContainer, 'marine', {
  onToggle: makeToggleHandler('marine'),
  onRefresh: makeRefreshHandler('marine'),
  onCaveats: makeCaveatsHandler('marine'),
});
const landBadge = mountBadge(badgesContainer, 'land', {
  onToggle: makeToggleHandler('land'),
  onRefresh: makeRefreshHandler('land'),
  onCaveats: makeCaveatsHandler('land'),
});

// Toggle-off (REQUIRED TEST SEAM #1/#3): reflect the store's optimistic
// `enabled` flip onto the badge immediately, and clear the domain's live map
// source so it renders zero features right away rather than waiting on a
// status event that, per FR5, is not expected to arrive while disabled.
// Re-enabling clears no source — the next `snapshot:{domain}` (resumed once
// `Store.applySnapshot`'s enabled-guard opens back up) repopulates it.
store.on('enabled:air', (payload) => {
  airBadge.setEnabled(payload as boolean);
  if (!payload) {
    clearAviationLayer(map);
  }
});
store.on('enabled:marine', (payload) => {
  marineBadge.setEnabled(payload as boolean);
  if (!payload) {
    clearMarineLayer(map);
  }
});
store.on('enabled:land', (payload) => {
  landBadge.setEnabled(payload as boolean);
  if (!payload) {
    clearLandLayer(map);
  }
});

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
  clearMarineLayer(map);
});

// Air/land/marine map sources+layers can only be added once the base style has
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
let marineLayerInitialized = false;
let pendingAirSnapshot: LayerSnapshot | null = null;
let pendingLandSnapshot: LayerSnapshot | null = null;
let pendingMarineSnapshot: LayerSnapshot | null = null;

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
let marineSseReceived = false;

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

// Marine gets the SAME cold-start REST fallback as air/land (the marine
// source/layers must exist as soon as the map is ready, even with zero
// features, so it can be populated purely by later SSE pushes — see the
// `initialLoadTasks` comment below) even though its LIVE updates stream from
// aisstream over SSE only.
function renderMarineSnapshot(snapshot: LayerSnapshot): void {
  marineBadge.update(snapshot.meta);
  if (!mapLoaded) {
    pendingMarineSnapshot = snapshot;
    return;
  }
  if (!marineLayerInitialized) {
    initMarineLayer(map, snapshot);
    initMarinePopup(map);
    marineLayerInitialized = true;
  } else {
    updateMarineLayer(map, snapshot);
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

// Marine source/symbol/ring layers + popup (frontend/06-marine-integrity).
// `status:marine` is meta-only (e.g. `reconnecting` on a dropped aisstream
// websocket) — badge only, no map source change.
store.on('snapshot:marine', (payload) => {
  marineSseReceived = true;
  renderMarineSnapshot(payload as LayerSnapshot);
});
store.on('status:marine', (payload) => {
  marineSseReceived = true;
  marineBadge.update(payload as LayerSnapshotMeta);
});

// Client-tick restyle (spec §9): `Store.tick` has already recomputed
// `deemphasized`/dropped the marine source's features; this just re-renders
// from that recomputed list. No-op before the marine layer/source exists.
store.on('tick:marine', (payload) => {
  if (!marineLayerInitialized) {
    return;
  }
  tickMarineLayer(map, payload as WireFeature[]);
});

// Exactly one EventSource for the app's lifetime (spec §3) — the Retry
// action (below) re-runs `connect()`, which is the one sanctioned exception
// (the prior connection has already failed fatally by the time Retry shows).
const sseClient = new SseClient(store);
mountConnectionBanner(document.body, store, () => {
  sseClient.connect();
});

// Client-tick de-emphasis/drop (spec §9): thresholds are sourced from
// `GET /api/config` once at bootstrap (`Store.setConfig`), then a
// `setInterval` (~5-10s band, `config.ts`) drives `Store.tick` for the
// lifetime of the app. `tick()` itself no-ops until `setConfig` has resolved,
// so a slow/failed config fetch never throws from inside the interval.
void fetchConfig()
  .then((config) => {
    store.setConfig(config);
  })
  .catch((err) => {
    console.warn('[zij] fetchConfig() failed:', err);
  });
setInterval(() => {
  store.tick(Date.now());
}, TICK_INTERVAL_MS);

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
  if (pendingMarineSnapshot) {
    const snapshot = pendingMarineSnapshot;
    pendingMarineSnapshot = null;
    renderMarineSnapshot(snapshot);
  }

  const initialLoadTasks: LayerLoadTask[] = [
    {
      label: 'air',
      load: () => fetchSnapshot('air'),
      render: (snapshot) => {
        if (!airSseReceived && store.getState().layers.air.enabled) {
          renderAirSnapshot(snapshot as LayerSnapshot);
        }
      },
    },
    {
      label: 'land',
      load: () => fetchSnapshot('land'),
      render: (snapshot) => {
        if (!landSseReceived && store.getState().layers.land.enabled) {
          renderLandSnapshot(snapshot as LayerSnapshot);
        }
      },
    },
    {
      label: 'marine',
      load: () => fetchSnapshot('marine'),
      render: (snapshot) => {
        if (!marineSseReceived && store.getState().layers.marine.enabled) {
          renderMarineSnapshot(snapshot as LayerSnapshot);
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
        render: (snapshot) => {
          if (store.getState().layers.air.enabled) {
            renderAirSnapshot(snapshot as LayerSnapshot);
          }
        },
      },
      {
        label: 'land',
        load: () => fetchSnapshot('land'),
        render: (snapshot) => {
          if (store.getState().layers.land.enabled) {
            renderLandSnapshot(snapshot as LayerSnapshot);
          }
        },
      },
      {
        label: 'marine',
        load: () => fetchSnapshot('marine'),
        render: (snapshot) => {
          if (store.getState().layers.marine.enabled) {
            renderMarineSnapshot(snapshot as LayerSnapshot);
          }
        },
      },
    ];
    await loadLayers(refreshTasks);
  })().catch((err) => {
    console.warn('[zij] refresh failed:', err);
  });
});
