import 'maplibre-gl/dist/maplibre-gl.css';
import './styles/tokens.css';
import { initMap } from './map/map';

// Entry point (spec §1): bootstrap the map. Store / SSE / UI mount arrive in
// later slices; slice 01 is the map walking skeleton only.
const container = document.getElementById('map');
if (!container) {
  throw new Error('Zij: #map container not found');
}
initMap(container);
