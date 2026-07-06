import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/tokens.css';
import './styles/layout.css';
import { initMap } from './map/map';
import { fetchSnapshot, refreshAll } from './api/client';
import { initAviationLayer, updateAviationLayer } from './map/layers/aviation';
import { initLandLayer, updateLandLayer } from './map/layers/land';
import { mountBadge } from './ui/badges';
import { loadLayers, type LayerLoadTask } from './app/loadLayers';
import type { LayerSnapshot } from './state/types';

// Entry point (spec §1): bootstrap the map, then (this slice) fetch the air +
// land snapshots, render their layers, mount the freshness/count badges, and
// wire the global "Refresh all" control. Store/SSE arrive in later slices —
// v0 is REST-only (poll-once refresh, no push).
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
const landBadge = mountBadge(badgesContainer, 'land');

// Failure isolation (spec FR10, issue #20): each domain's fetch+render is an
// independent `LayerLoadTask` run through `loadLayers`, so one domain
// rejecting never blocks the other from rendering (see `app/loadLayers.ts`).
map.on('load', () => {
  const initialLoadTasks: LayerLoadTask[] = [
    {
      label: 'air',
      load: () => fetchSnapshot('air'),
      render: (snapshot) => {
        const airSnapshot = snapshot as LayerSnapshot;
        initAviationLayer(map, airSnapshot);
        airBadge.update(airSnapshot.meta);
      },
    },
    {
      label: 'land',
      load: () => fetchSnapshot('land'),
      render: (snapshot) => {
        const landSnapshot = snapshot as LayerSnapshot;
        initLandLayer(map, landSnapshot);
        landBadge.update(landSnapshot.meta);
      },
    },
  ];
  void loadLayers(initialLoadTasks);
});

const refreshButton = document.querySelector<HTMLButtonElement>('[data-testid="refresh-all"]');
refreshButton?.addEventListener('click', () => {
  void (async () => {
    await refreshAll();
    const refreshTasks: LayerLoadTask[] = [
      {
        label: 'air',
        load: () => fetchSnapshot('air'),
        render: (snapshot) => {
          const airSnapshot = snapshot as LayerSnapshot;
          updateAviationLayer(map, airSnapshot);
          airBadge.update(airSnapshot.meta);
        },
      },
      {
        label: 'land',
        load: () => fetchSnapshot('land'),
        render: (snapshot) => {
          const landSnapshot = snapshot as LayerSnapshot;
          updateLandLayer(map, landSnapshot);
          landBadge.update(landSnapshot.meta);
        },
      },
    ];
    await loadLayers(refreshTasks);
  })().catch((err) => {
    console.warn('[zij] refresh failed:', err);
  });
});
