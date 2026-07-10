// AppState + typed event-emitter (spec §9). Single app-state object; SSE
// events (`applySnapshot`/`applyLayerStatus`/`applyRegionChanged`) and user
// actions (`setConnection` is driven by `sse/client.ts`'s open/error handling)
// are the *only* writers. Renderers subscribe via `on()`, never poll.
//
// Hand-rolled pub-sub (~20 lines, spec §9 rationale: not "reinventing a
// solved problem" the way SSE framing is — a tiny in-memory event bus has no
// sharp edges worth pulling a dependency for).

import { toggleLayer as postToggleLayer } from '../api/client';
import { tickLayerFeatures } from './derive';
import type { AppConfig, Domain, LayerSnapshot, LayerSnapshotMeta } from './types';

/** Domains the client-tick recompute applies to (spec §9/§2) — land is the
 * one domain exempt from ticking (rebuilt once per snapshot only). */
const TICKED_DOMAINS = ['air', 'marine'] as const;

export type Connection = 'connecting' | 'open' | 'lost' | 'failed';

export interface LayerState {
  enabled: boolean;
  meta: LayerSnapshotMeta | null;
  features: LayerSnapshot['features'];
  /** `Date.now()` when this layer's state was last written — tick basis for
   * later slices' de-emphasis/drop computation (§9); unused by this slice. */
  receivedAt: number;
}

export interface RegionChangedPayload {
  region_id: string;
  bbox: number[];
}

export interface AppState {
  activeRegion: RegionChangedPayload | null;
  layers: Record<Domain, LayerState>;
  connection: Connection;
}

type Listener = (payload: unknown) => void;

function emptyLayerState(): LayerState {
  return { enabled: true, meta: null, features: [], receivedAt: 0 };
}

export class Store {
  private state: AppState = {
    activeRegion: null,
    layers: {
      air: emptyLayerState(),
      marine: emptyLayerState(),
      land: emptyLayerState(),
    },
    connection: 'connecting',
  };

  private listeners = new Map<string, Set<Listener>>();

  /** Per-layer de-emphasize/drop thresholds, sourced once from `GET
   * /api/config` (spec §9 "GET /api/config layers shape") — `tick()` is a
   * no-op until this has been set at least once. */
  private tickConfig: AppConfig | null = null;

  /** Subscribes `fn` to `event`; returns an unsubscribe function. */
  on(event: string, fn: Listener): () => void {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(fn);
    return () => {
      set?.delete(fn);
    };
  }

  private emit(event: string, payload?: unknown): void {
    this.listeners.get(event)?.forEach((fn) => fn(payload));
  }

  getState(): Readonly<AppState> {
    return this.state;
  }

  /**
   * Idempotent full replace — full-state-on-connect (ADR-12) needs no special
   * reconnect handling beyond calling this on every `snapshot` event, whether
   * it is the first snapshot or a re-emitted one after reconnect.
   */
  applySnapshot(domain: Domain, snap: LayerSnapshot): void {
    // A disabled layer expects no further SSE (spec §7 FR5) — a stray
    // snapshot (e.g. a race with an in-flight toggle) must not resurrect it;
    // `toggleLayer` is the only path back to `enabled:true`.
    if (!this.state.layers[domain].enabled) {
      return;
    }
    this.state.layers[domain] = {
      enabled: true,
      meta: snap.meta,
      features: snap.features,
      receivedAt: Date.now(),
    };
    this.emit(`snapshot:${domain}`, snap);
  }

  /** Meta-only update (no feature payload) — e.g. loading/rate-limited/error
   * status transitions between snapshots. */
  applyLayerStatus(domain: Domain, meta: LayerSnapshotMeta): void {
    if (!this.state.layers[domain].enabled) {
      return;
    }
    const prev = this.state.layers[domain];
    this.state.layers[domain] = { ...prev, meta };
    this.emit(`status:${domain}`, meta);
  }

  /**
   * Layer toggle (spec §7 FR5, §9 sketch): optimistic local set — flip
   * `enabled` and emit `enabled:{domain}` immediately, so the badge/map
   * source react without waiting on the network — then fire the `POST`
   * (fire-and-forget; a real backend confirms via the next SSE status event,
   * per §9 "reconciled by next status event"). A failed POST is logged, not
   * rolled back — the emitted `enabled:{domain}` state (and, on disable,
   * `applySnapshot`/`applyLayerStatus`'s guard above) is what actually stops
   * the frontend from expecting further updates, independent of whether the
   * backend request itself succeeds.
   */
  toggleLayer(domain: Domain, enabled: boolean): void {
    const prev = this.state.layers[domain];
    this.state.layers[domain] = { ...prev, enabled };
    this.emit(`enabled:${domain}`, enabled);
    void postToggleLayer(domain, enabled).catch((err) => {
      console.warn(`[zij] toggleLayer(${domain}) failed:`, err);
    });
  }

  /** Clears every layer's last-known DATA (spec §6: "all layer panes clear
   * immediately" on region change) and emits `region:changed`. Each domain's
   * `enabled` toggle is preserved (#98): a region change is not a path back
   * to `enabled: true` — `toggleLayer` is the only such path (same principle
   * as `applySnapshot`'s disabled-domain guard above). Resetting it silently
   * re-opened the snapshot guard while the badge's `data-enabled` DOM stayed
   * stale at "false". */
  applyRegionChanged(payload: RegionChangedPayload): void {
    this.state.activeRegion = payload;
    (Object.keys(this.state.layers) as Domain[]).forEach((domain) => {
      this.state.layers[domain] = { ...emptyLayerState(), enabled: this.state.layers[domain].enabled };
    });
    this.emit('region:changed', payload);
  }

  setConnection(c: Connection): void {
    this.state.connection = c;
    this.emit('connection', c);
  }

  /** Stores the config-sourced de-emphasize/drop thresholds `tick()` reads
   * (spec §9). Safe to call more than once (e.g. a later `GET /api/config`
   * refresh) — later calls simply replace the thresholds `tick()` sees next. */
  setConfig(config: AppConfig): void {
    this.tickConfig = config;
  }

  /**
   * Client-tick recompute (spec §9 `tick(now)`): re-derives `deemphasized`
   * for air + marine's currently-held features from the config-sourced
   * thresholds, dropping marine vessels whose age exceeds
   * `drop_after_s` entirely (spec §2 Marine; air has no drop threshold).
   * Land is exempt (rebuilt once per snapshot only). No-op until
   * `setConfig()` has supplied thresholds, or for a domain with zero
   * currently-held features (nothing to recompute).
   */
  tick(now: number): void {
    if (!this.tickConfig) {
      return;
    }
    for (const domain of TICKED_DOMAINS) {
      const layer = this.state.layers[domain];
      if (!layer.enabled || layer.features.length === 0) {
        continue;
      }
      const thresholds = this.tickConfig.layers[domain];
      const dropAfterS = domain === 'marine' ? this.tickConfig.layers.marine.drop_after_s : undefined;
      const nextFeatures = tickLayerFeatures(layer.features, now, thresholds.deemphasize_after_s, dropAfterS);
      this.state.layers[domain] = { ...layer, features: nextFeatures };
      this.emit(`tick:${domain}`, nextFeatures);
    }
  }
}
