// EventSource wrapper: dispatch, reconnect/lost detection (spec §3). Thin
// wrapper over the browser-native EventSource — no reconnect/backoff
// reimplementation (ADR-2 already rejected that once, server-side; the
// client gets the same native benefit for free).

import type { Store } from '../state/store';
import type { Domain, LayerSnapshot, LayerSnapshotMeta } from '../state/types';

const DEFAULT_URL = '/api/events';

export class SseClient {
  private es: EventSource;

  constructor(
    private readonly store: Store,
    private readonly url: string = DEFAULT_URL,
  ) {
    this.es = this.open();
  }

  private open(): EventSource {
    const es = new EventSource(this.url);

    es.addEventListener('snapshot', (e) => {
      const snap = JSON.parse((e as MessageEvent).data) as LayerSnapshot;
      this.store.applySnapshot(snap.meta.layer as Domain, snap);
    });
    es.addEventListener('layer_status', (e) => {
      const meta = JSON.parse((e as MessageEvent).data) as LayerSnapshotMeta;
      this.store.applyLayerStatus(meta.layer as Domain, meta);
    });
    es.addEventListener('region_changed', (e) => {
      this.store.applyRegionChanged(JSON.parse((e as MessageEvent).data));
    });
    // 'ping' — no listener needed; it's sse-starlette's comment/heartbeat.
    // Absence of any event for longer than the server's ping interval is
    // already covered by onerror/readyState below.

    es.onopen = () => {
      this.store.setConnection('open');
    };
    es.onerror = () => {
      // readyState CONNECTING: native auto-retry in flight -> "lost" (reconnecting).
      // readyState CLOSED: fatal (non-2xx / bad content-type on connect) -> native
      // retry will NOT resume; the manual "Retry" action re-runs `connect()`.
      this.store.setConnection(es.readyState === EventSource.CLOSED ? 'failed' : 'lost');
    };

    return es;
  }

  /** Closes the current (dead, once fatally failed) connection and opens a
   * fresh one — this is what the manual "Retry" action calls. */
  connect(): void {
    this.es.close();
    this.es = this.open();
  }
}
