// AppState + typed event-emitter (spec §9). Single app-state object; SSE
// events (`applySnapshot`/`applyLayerStatus`/`applyRegionChanged`) and user
// actions (`setConnection` is driven by `sse/client.ts`'s open/error handling)
// are the *only* writers. Renderers subscribe via `on()`, never poll.
//
// Hand-rolled pub-sub (~20 lines, spec §9 rationale: not "reinventing a
// solved problem" the way SSE framing is — a tiny in-memory event bus has no
// sharp edges worth pulling a dependency for).

import type { Domain, LayerSnapshot, LayerSnapshotMeta } from './types';

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
    const prev = this.state.layers[domain];
    this.state.layers[domain] = { ...prev, meta };
    this.emit(`status:${domain}`, meta);
  }

  /** Clears every layer's last-known state (spec §6: "all layer panes clear
   * immediately" on region change) and emits `region:changed`. */
  applyRegionChanged(payload: RegionChangedPayload): void {
    this.state.activeRegion = payload;
    (Object.keys(this.state.layers) as Domain[]).forEach((domain) => {
      this.state.layers[domain] = emptyLayerState();
    });
    this.emit('region:changed', payload);
  }

  setConnection(c: Connection): void {
    this.state.connection = c;
    this.emit('connection', c);
  }
}
