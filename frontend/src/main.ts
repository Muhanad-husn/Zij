import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/tokens.css';
import './styles/layout.css';
import { initMap } from './map/map';
import { fetchSnapshot, refreshAll } from './api/client';
import { initAviationLayer, updateAviationLayer } from './map/layers/aviation';
import { initLandLayer, updateLandLayer } from './map/layers/land';
import { mountBadge } from './ui/badges';

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

map.on('load', () => {
  void (async () => {
    const [airSnapshot, landSnapshot] = await Promise.all([fetchSnapshot('air'), fetchSnapshot('land')]);
    initAviationLayer(map, airSnapshot);
    initLandLayer(map, landSnapshot);
    airBadge.update(airSnapshot.meta);
    landBadge.update(landSnapshot.meta);
  })().catch((err) => {
    console.warn('[zij] initial snapshot load failed:', err);
  });
});

const refreshButton = document.querySelector<HTMLButtonElement>('[data-testid="refresh-all"]');
refreshButton?.addEventListener('click', () => {
  void (async () => {
    await refreshAll();
    const [airSnapshot, landSnapshot] = await Promise.all([fetchSnapshot('air'), fetchSnapshot('land')]);
    updateAviationLayer(map, airSnapshot);
    updateLandLayer(map, landSnapshot);
    airBadge.update(airSnapshot.meta);
    landBadge.update(landSnapshot.meta);
  })().catch((err) => {
    console.warn('[zij] refresh failed:', err);
  });
});
