// Shared marine popup (spec §2 Marine "Popup" / Performance budget: "ONE
// shared Popup instance, opened on a layer `click` handler"). MMSI/name/SOG/
// COG plus inline flag naming when `integrity_flags` is non-empty (FR3/FR9).

import maplibregl, { type MapGeoJSONFeature, type MapLayerMouseEvent, type Map as MapLibreMap } from 'maplibre-gl';
import { MARINE_LAYER_ID } from './layers/marine';

/** Human-readable names for the known `IntegrityFlag` values
 * (feature-schema.md) — falls back to a de-slugged raw value for any future
 * flag this popup doesn't yet know about. */
const FLAG_LABELS: Record<string, string> = {
  spoof_suspect_on_land: 'Spoof suspected (position on land)',
  implausible_kinematics: 'Implausible kinematics (speed/course jump)',
};

function humanizeFlag(flag: string): string {
  return FLAG_LABELS[flag] ?? flag.replace(/_/g, ' ');
}

function textEl(testId: string, text: string): HTMLDivElement {
  const el = document.createElement('div');
  el.setAttribute('data-testid', testId);
  el.textContent = text;
  return el;
}

/**
 * MapLibre tiles GeoJSON sources internally (geojson-vt) — any non-primitive
 * property value comes back JSON-STRINGIFIED in the tiled representation
 * that click events / `queryRenderedFeatures` read (as opposed to
 * `source.serialize().data`, which returns the original untiled data
 * verbatim). Normalizes a possibly-stringified array property back to a real
 * array; a bad/missing value safely resolves to `[]` rather than throwing.
 */
function normalizeFlags(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw as string[];
  }
  if (typeof raw === 'string' && raw.length > 0) {
    try {
      const parsed: unknown = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as string[]) : [];
    } catch {
      return [];
    }
  }
  return [];
}

/** Builds the popup's DOM content from one clicked `marine-vessels`
 * feature's GeoJSON properties (spec §2: MMSI/name/SOG/COG/age, flag
 * name(s) inline when present). Reads SOG/COG off the FLATTENED top-level
 * properties (`wireToGeoJson` spreads `...f.attrs`, so these are primitives)
 * rather than `properties.attrs` — the tiled `attrs` object comes back
 * JSON-stringified in a click event's feature properties, so reading
 * `.sog_kn` off it would silently read `undefined` off a string. */
function buildPopupContent(properties: Record<string, unknown>): HTMLElement {
  const container = document.createElement('div');
  container.setAttribute('data-testid', 'marine-popup');

  const sourceId = String(properties.source_id ?? '');
  const mmsiEl = textEl('popup-mmsi', sourceId);
  container.appendChild(mmsiEl);

  const label = properties.label as string | null;
  if (label) {
    const labelEl = document.createElement('div');
    labelEl.textContent = label;
    container.appendChild(labelEl);
  }

  const sogKn = properties.sog_kn;
  container.appendChild(textEl('popup-sog', `SOG ${sogKn ?? '—'} kn`));

  const cogDeg = properties.cog_deg;
  container.appendChild(textEl('popup-cog', `COG ${cogDeg ?? '—'}°`));

  const positionAgeS = properties.position_age_s;
  if (positionAgeS !== undefined && positionAgeS !== null) {
    container.appendChild(textEl('popup-age', `${Math.round(Number(positionAgeS))}s ago`));
  }

  const flags = normalizeFlags(properties.integrity_flags);
  if (flags.length > 0) {
    const flagsEl = document.createElement('div');
    flagsEl.setAttribute('data-testid', 'popup-flags');
    flagsEl.setAttribute('data-flags', flags.join(','));
    flagsEl.textContent = flags.map(humanizeFlag).join(', ');
    container.appendChild(flagsEl);
  }

  return container;
}

/**
 * Wires the ONE shared marine `Popup` instance to `marine-vessels` clicks
 * (spec §2 Performance budget). Call once, after the marine layer has been
 * added to `map`. `closeOnClick: false` — this handler is the sole owner of
 * the popup's content/position, so clicking a new feature always swaps the
 * SAME instance's content rather than racing MapLibre's own close-on-click
 * teardown.
 */
export function initMarinePopup(map: MapLibreMap): void {
  const popup = new maplibregl.Popup({ closeButton: true, closeOnClick: false });

  map.on('click', MARINE_LAYER_ID, (e: MapLayerMouseEvent) => {
    const feature: MapGeoJSONFeature | undefined = e.features?.[0];
    if (!feature || feature.geometry.type !== 'Point') {
      return;
    }
    const [lon, lat] = feature.geometry.coordinates as [number, number];
    const content = buildPopupContent(feature.properties ?? {});
    popup.setLngLat([lon, lat]).setDOMContent(content).addTo(map);
  });

  map.on('mouseenter', MARINE_LAYER_ID, () => {
    map.getCanvas().style.cursor = 'pointer';
  });
  map.on('mouseleave', MARINE_LAYER_ID, () => {
    map.getCanvas().style.cursor = '';
  });
}
